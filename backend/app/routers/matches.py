"""Matchmaking and live match action endpoints (spec §27.3, §27.4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.common import rate_limit
from app.common.api import Caller, get_container, player, run_mutation
from app.common.errors import ApiError, ErrorCode
from app.common.idempotency import resolve_key
from app.container import Container
from app.matches.model import Mode
from app.moderation.question_reports import QuestionReportReason
from app.moderation.risk import RiskSignal, watch

# Stale/forged answer submissions and answer flooding feed the risk score (spec §28.4).
MALFORMED_ANSWER = {ErrorCode.RATE_LIMITED, ErrorCode.INVALID_OPTION, ErrorCode.ROUND_EXPIRED,
                    ErrorCode.ROUND_NOT_ACTIVE, ErrorCode.NOT_MATCH_PARTICIPANT}

router = APIRouter(prefix="/v1")


class JoinRequest(BaseModel):
    request_id: str
    # Median of 5–7 authenticated pings; used for grouping only (spec §21.2).
    median_rtt_ms: int = Field(ge=0, le=10_000)


class MutationBody(BaseModel):
    request_id: str


class ClientDiagnostics(BaseModel):
    displayed_at_monotonic_ms: int | None = None
    tap_at_monotonic_ms: int | None = None


class AnswerRequest(BaseModel):
    request_id: str
    round_id: str = Field(max_length=64)
    option_id: str = Field(max_length=96)
    rtdb_shard_id: str | None = Field(default=None, max_length=16)
    client_diagnostics: ClientDiagnostics | None = None  # debugging only, never authoritative


def _mode(mode: str) -> Mode:
    try:
        return Mode(mode.upper())
    except ValueError as exc:
        raise ApiError(ErrorCode.NOT_FOUND) from exc


# ---------------------------------------------------------------------------------------------- matchmaking
@router.post("/matchmaking/{mode}/join")
async def join_queue(mode: str, body: JoinRequest, request: Request, caller: Caller = Depends(player),
                     c: Container = Depends(get_container)) -> dict:
    queue_mode = _mode(mode)
    async with watch(c, caller.uid, RiskSignal.QUEUE_MANIPULATION, codes={ErrorCode.RATE_LIMITED}):
        await c.rate_limiter.hit(rate_limit.QUEUE_JOIN, caller.uid)

    async def handler() -> dict:
        return await c.matchmaking.join(caller.uid, caller.user, queue_mode, body.median_rtt_ms, body.request_id)

    return await run_mutation(c, request, caller, f"matchmaking.join.{queue_mode.value}", body.model_dump(), handler)


@router.delete("/matchmaking/{mode}/leave")
async def leave_queue(mode: str, body: MutationBody, request: Request, caller: Caller = Depends(player),
                      c: Container = Depends(get_container)) -> dict:
    queue_mode = _mode(mode)
    async with watch(c, caller.uid, RiskSignal.QUEUE_MANIPULATION, codes={ErrorCode.RATE_LIMITED}):
        await c.rate_limiter.hit(rate_limit.QUEUE_LEAVE, caller.uid)

    async def handler() -> dict:
        return await c.matchmaking.leave(caller.uid, queue_mode)

    return await run_mutation(c, request, caller, f"matchmaking.leave.{queue_mode.value}", body.model_dump(),
                              handler)


@router.get("/matchmaking/status")
async def queue_status(caller: Caller = Depends(player), c: Container = Depends(get_container)) -> dict:
    return await c.matchmaking.status(caller.uid)


# ---------------------------------------------------------------------------------------------- match actions
@router.get("/matches/{match_id}")
async def get_match(match_id: str, caller: Caller = Depends(player), c: Container = Depends(get_container)) -> dict:
    return await c.matches.view(caller.uid, match_id)


@router.post("/matches/{match_id}/answer")
async def answer(match_id: str, body: AnswerRequest, request: Request, caller: Caller = Depends(player),
                 c: Container = Depends(get_container)) -> dict:
    # Server receipt time is recorded first; nothing the client sends affects ordering (spec §22.3).
    received_at = c.clock.now_ms()
    request_id = resolve_key(request.headers.get("x-idempotency-key"), body.request_id)
    async with watch(c, caller.uid, RiskSignal.MALFORMED_REQUEST, codes=MALFORMED_ANSWER,
                     evidence={"match_id": match_id}):
        await c.rate_limiter.hit(rate_limit.ANSWER, caller.uid)
        # Idempotency lives in the canonical match transaction (the stored answer is the replay record).
        return await c.matches.answer(caller.uid, match_id, body.round_id, body.option_id, request_id, received_at,
                                      body.rtdb_shard_id)


@router.post("/matches/{match_id}/sync")
async def sync(match_id: str, caller: Caller = Depends(player), c: Container = Depends(get_container)) -> dict:
    await c.rate_limiter.hit(rate_limit.SYNC, caller.uid)
    return await c.matches.sync(caller.uid, match_id)


@router.post("/matches/{match_id}/leave")
async def leave_match(match_id: str, body: MutationBody, request: Request, caller: Caller = Depends(player),
                      c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        return await c.matches.leave(caller.uid, match_id)

    return await run_mutation(c, request, caller, f"matches.leave.{match_id}", body.model_dump(), handler)


class ReactionRequest(BaseModel):
    request_id: str
    round_id: str = Field(max_length=64)
    reaction_id: str = Field(max_length=32)  # catalog ID only; free text is never accepted (spec §5)


class QuestionReportRequest(BaseModel):
    request_id: str
    round_id: str = Field(max_length=64)
    reason: QuestionReportReason


@router.post("/matches/{match_id}/reaction")
async def react(match_id: str, body: ReactionRequest, caller: Caller = Depends(player),
                c: Container = Depends(get_container)) -> dict:
    await c.rate_limiter.hit(rate_limit.REACTION, caller.uid)
    return await c.matches.react(caller.uid, match_id, body.round_id, body.reaction_id)


@router.post("/matches/{match_id}/question-report")
async def report_question(match_id: str, body: QuestionReportRequest, request: Request,
                          caller: Caller = Depends(player), c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        await c.rate_limiter.hit(rate_limit.QUESTION_REPORT, caller.uid)
        shown = await c.matches.shown_question(caller.uid, match_id, body.round_id)
        return await c.question_reports.report(caller.uid, gid=shown["gid"], version=int(shown["v"]),
                                               language=shown["language"], mode=shown["mode"], reason=body.reason,
                                               match_id=match_id)

    return await run_mutation(c, request, caller, f"matches.question_report.{match_id}", body.model_dump(), handler)
