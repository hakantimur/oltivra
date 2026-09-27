"""Block, report and shared account deletion endpoints (spec §6.1, §27.5, §29, §30)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.common import rate_limit
from app.common.api import Caller, authenticated, get_container, player, run_mutation
from app.container import Container
from app.moderation.safety import PlayerReportReason

router = APIRouter(prefix="/v1")


class MutationBody(BaseModel):
    request_id: str


class PlayerReportRequest(BaseModel):
    request_id: str
    target_public_id: str = Field(max_length=32)
    reason: PlayerReportReason
    match_id: str | None = Field(default=None, max_length=64)


@router.get("/blocks")
async def list_blocks(caller: Caller = Depends(player), c: Container = Depends(get_container)) -> dict:
    uids = await c.safety.blocked_by_me(caller.uid)
    users = await c.store.get_many([f"users/{u}" for u in uids]) if uids else []
    items = []
    for user in users:
        if user and user.get("username_display"):
            items.append({"public_id": user["public_id"], "username": user["username_display"],
                          "avatar_id": user.get("avatar_id")})
    return {"schema_version": 1, "blocked": items}


@router.post("/blocks/{public_id}")
async def block(public_id: str, body: MutationBody, request: Request, caller: Caller = Depends(player),
                c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        target = await c.profiles.uid_for_public_id(public_id)
        await c.safety.block(caller.uid, target)
        return {"schema_version": 1, "blocked": True}

    return await run_mutation(c, request, caller, f"blocks.add.{public_id}", body.model_dump(), handler)


@router.delete("/blocks/{public_id}")
async def unblock(public_id: str, body: MutationBody, request: Request, caller: Caller = Depends(player),
                  c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        target = await c.profiles.uid_for_public_id(public_id)
        await c.safety.unblock(caller.uid, target)
        return {"schema_version": 1, "blocked": False}

    return await run_mutation(c, request, caller, f"blocks.remove.{public_id}", body.model_dump(), handler)


@router.post("/player-reports")
async def report_player(body: PlayerReportRequest, request: Request, caller: Caller = Depends(player),
                        c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        await c.rate_limiter.hit(rate_limit.PLAYER_REPORT, caller.uid)
        target = await c.profiles.uid_for_public_id(body.target_public_id)
        report_id = await c.safety.report_player(caller.uid, target, body.reason, {"match_id": body.match_id})
        return {"schema_version": 1, "report_id": report_id, "status": "RECEIVED"}

    return await run_mutation(c, request, caller, "player_reports", body.model_dump(mode="json"), handler)


@router.delete("/account")
async def delete_account(body: MutationBody, request: Request, caller: Caller = Depends(authenticated),
                         c: Container = Depends(get_container)) -> dict:
    """Deletes the shared account across participating products (spec §30.1). Requires recent sign-in."""
    async def handler() -> dict:
        return await c.deletion.request(caller.uid, caller.token)

    return await run_mutation(c, request, caller, "account.delete", body.model_dump(), handler)


@router.get("/account/deletion")
async def deletion_status(caller: Caller = Depends(authenticated), c: Container = Depends(get_container)) -> dict:
    doc = await c.store.get(f"deletion_requests/{caller.uid}")
    return {"schema_version": 1, "status": (doc or {}).get("status", "NONE")}
