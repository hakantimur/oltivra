"""Admin moderation (spec §11 areas 9, 10, 15; §28.4; §29): question-report and player-report queues, user view,
sanctions and the anti-cheat risk review queue. Every write is audit-logged."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.common.api import Caller, get_container
from app.common.errors import ApiError, ErrorCode
from app.common.store.docstore import Query as DocQuery
from app.container import Container
from app.moderation.sanctions import IRREVERSIBLE, SanctionKind
from app.questions.models import QuestionStatus
from app.routers.admin import _rebuild_manifests, admin_caller

router = APIRouter(prefix="/admin/v1", tags=["admin-moderation"])

MAX_DURATION_MS = 365 * 86_400_000


class SanctionIn(BaseModel):
    kind: SanctionKind
    reason_code: str = Field(min_length=3, max_length=120)
    duration_ms: int | None = Field(default=None, ge=60_000, le=MAX_DURATION_MS)
    confirm_irreversible: bool = False


class PlayerReportResolveIn(BaseModel):
    action: Literal["DISMISS", "SANCTION"]
    reason_code: str = Field(min_length=3, max_length=120)
    sanction: SanctionIn | None = None


class QuestionReportResolveIn(BaseModel):
    action: Literal["DISMISS", "QUARANTINE", "RETIRE", "RESTORE"]
    reason_code: str = Field(min_length=3, max_length=120)


class LiftIn(BaseModel):
    reason_code: str = Field(min_length=3, max_length=120)


class RiskReviewIn(BaseModel):
    reason_code: str = Field(min_length=3, max_length=120)
    reset_score: bool = False


async def _resolve_uid(c: Container, ref: str) -> str:
    """Accept a UID or a public ID (the admin UI mostly sees public IDs from reports)."""
    if await c.store.get(f"users/{ref}"):
        return ref
    mapping = await c.store.get(f"public_ids/{ref}")
    if mapping and mapping.get("uid") and not mapping.get("is_bot"):
        return mapping["uid"]
    raise ApiError(ErrorCode.NOT_FOUND)


def _user_card(user: dict | None) -> dict | None:
    if not user:
        return None
    return {"uid": user.get("uid"), "public_id": user.get("public_id"), "username": user.get("username_display"),
            "avatar_id": user.get("avatar_id"), "status": user.get("status", "ACTIVE")}


async def _apply(c: Container, uid: str, body: SanctionIn, actor: str) -> dict:
    if body.kind in IRREVERSIBLE and not body.confirm_irreversible:
        raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "confirm_irreversible_required"})
    return await c.sanctions.apply(uid, body.kind, actor=actor, reason_code=body.reason_code,
                                   duration_ms=body.duration_ms)


# ---------------------------------------------------------------------------------------------- player reports


@router.get("/player-reports")
async def player_reports(status: Literal["OPEN", "RESOLVED", "DISMISSED"] = "OPEN",
                         limit: int = Query(default=50, ge=1, le=200), caller: Caller = Depends(admin_caller),
                         c: Container = Depends(get_container)) -> dict:
    rows = await c.store.query(DocQuery("player_reports").filter("status", "==", status)
                               .order("created_at_ms", "desc").take(limit))
    reports = [r.data for r in rows]
    uids = sorted({r["target_uid"] for r in reports} | {r["reporter_uid"] for r in reports})
    users = dict(zip(uids, await c.store.get_many([f"users/{u}" for u in uids]), strict=True)) if uids else {}
    per_target: dict[str, int] = {}
    for report in reports:
        per_target[report["target_uid"]] = per_target.get(report["target_uid"], 0) + 1
    items = [{"report_id": r["report_id"], "reason": r["reason"], "status": r["status"],
              "created_at_ms": r["created_at_ms"], "context": r.get("context") or {},
              "target": _user_card(users.get(r["target_uid"])) or {"uid": r["target_uid"]},
              "reporter": _user_card(users.get(r["reporter_uid"])) or {"uid": r["reporter_uid"]},
              "open_reports_against_target": per_target[r["target_uid"]]} for r in reports]
    return {"schema_version": 1, "items": items}


@router.post("/player-reports/{report_id}/resolve")
async def resolve_player_report(report_id: str, body: PlayerReportResolveIn, caller: Caller = Depends(admin_caller),
                                c: Container = Depends(get_container)) -> dict:
    report = await c.store.get(f"player_reports/{report_id}")
    if not report:
        raise ApiError(ErrorCode.NOT_FOUND)
    if report["status"] != "OPEN":
        raise ApiError(ErrorCode.CONFLICT, detail={"reason": "already_resolved"})
    sanction = None
    if body.action == "SANCTION":
        if not body.sanction:
            raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "sanction_required"})
        sanction = await _apply(c, report["target_uid"], body.sanction, caller.uid)
    status = "RESOLVED" if sanction else "DISMISSED"
    await c.store.update(f"player_reports/{report_id}", {
        "status": status, "resolved_by": caller.uid, "resolved_at_ms": c.clock.now_ms(),
        "resolution": body.reason_code, "sanction_id": sanction["sanction_id"] if sanction else None})
    await c.audit.record(actor=caller.uid, action=f"PLAYER_REPORT_{status}", subject=f"player_report:{report_id}",
                         reason_code=body.reason_code)
    return {"schema_version": 1, "status": status, "sanction": sanction}


# ---------------------------------------------------------------------------------------------- question reports


@router.get("/question-reports")
async def question_reports(limit: int = Query(default=50, ge=1, le=200), caller: Caller = Depends(admin_caller),
                           c: Container = Depends(get_container)) -> dict:
    rows = await c.store.query(DocQuery("question_report_counters").order("unique_reporters", "desc").take(limit))
    counters = [r.data for r in rows if r.data.get("review_status", "OPEN") == "OPEN"]
    gids = [x["question_group_id"] for x in counters]
    groups = await c.store.get_many([f"question_groups/{g}" for g in gids]) if gids else []
    queue = {r.id: r.data for r in await c.store.query(DocQuery("moderation_queue")
                                                        .filter("kind", "==", "QUESTION_QUARANTINE"))}
    items = []
    for counter, group in zip(counters, groups, strict=True):
        gid, version = counter["question_group_id"], counter["question_version"]
        reasons = {k.removeprefix("reports_").upper(): v for k, v in counter.items()
                   if k.startswith("reports_") and isinstance(v, int)}
        items.append({"question_group_id": gid, "question_version": version, "reports": counter.get("reports", 0),
                      "unique_reporters": counter.get("unique_reporters", 0), "by_reason": reasons,
                      "status": (group or {}).get("status"), "current_version": (group or {}).get("version"),
                      "auto_quarantined": f"question_{gid}_{version}" in queue})
    return {"schema_version": 1, "items": items}


@router.get("/question-reports/{group_id}/{version}")
async def question_report_detail(group_id: str, version: int, caller: Caller = Depends(admin_caller),
                                 c: Container = Depends(get_container)) -> dict:
    rows = await c.store.query(DocQuery("question_reports").filter("question_group_id", "==", group_id)
                               .filter("question_version", "==", version).order("created_at_ms", "desc").take(200))
    # Reporter identity is not needed to judge content; only language/mode/reason are shown.
    reports = [{k: r.data.get(k) for k in ("report_id", "reason", "language", "mode", "created_at_ms", "status")}
               for r in rows]
    return {"schema_version": 1, "counter": await c.store.get(f"question_report_counters/{group_id}_{version}"),
            "reports": reports, "impressions": await c.question_reports.impressions(group_id, version)}


@router.post("/question-reports/{group_id}/{version}/resolve")
async def resolve_question_report(group_id: str, version: int, body: QuestionReportResolveIn,
                                  caller: Caller = Depends(admin_caller), c: Container = Depends(get_container)
                                  ) -> dict:
    group = await c.question_repo.get_group(group_id)
    if not group:
        raise ApiError(ErrorCode.NOT_FOUND)
    target = {"QUARANTINE": QuestionStatus.QUARANTINED, "RETIRE": QuestionStatus.RETIRED,
              "RESTORE": QuestionStatus.ACTIVE}.get(body.action)
    if target and group["version"] != version:
        raise ApiError(ErrorCode.CONFLICT, detail={"reason": "version_superseded", "current": group["version"]})
    if target:
        group = await c.question_repo.transition(group_id, target, caller.uid, body.reason_code)
        await _rebuild_manifests(c)
    now = c.clock.now_ms()
    counter = f"question_report_counters/{group_id}_{version}"
    if await c.store.get(counter):
        await c.store.update(counter, {"review_status": "REVIEWED", "reviewed_by": caller.uid,
                                       "reviewed_at_ms": now, "review_action": body.action})
    queue = f"moderation_queue/question_{group_id}_{version}"
    if await c.store.get(queue):
        await c.store.update(queue, {"status": "RESOLVED", "resolved_by": caller.uid, "resolved_at_ms": now})
    rows = await c.store.query(DocQuery("question_reports").filter("question_group_id", "==", group_id)
                               .filter("question_version", "==", version).filter("status", "==", "OPEN"))
    for row in rows:
        await c.store.update(row.path, {"status": "RESOLVED", "resolution": body.action})
    await c.audit.record(actor=caller.uid, action=f"QUESTION_REPORT_{body.action}", subject=f"question:{group_id}",
                         reason_code=body.reason_code, detail={"version": version})
    return {"schema_version": 1, "action": body.action, "status": group["status"], "resolved_reports": len(rows)}


# ---------------------------------------------------------------------------------------------- users & sanctions


@router.get("/users")
async def search_users(q: str = Query(min_length=2, max_length=32), caller: Caller = Depends(admin_caller),
                       c: Container = Depends(get_container)) -> dict:
    from app.friends.service import PREFIX_END
    from app.usernames.rules import normalize

    norm = normalize(q)
    rows = await c.store.query(DocQuery("username_registry").filter("name", ">=", norm)
                               .filter("name", "<", norm + PREFIX_END).take(25))
    uids = [r.data["uid"] for r in rows if r.data.get("uid") and not r.data.get("is_bot")]
    users = await c.store.get_many([f"users/{u}" for u in uids]) if uids else []
    return {"schema_version": 1, "items": [_user_card(u) for u in users if u]}


@router.get("/users/{ref}")
async def user_view(ref: str, caller: Caller = Depends(admin_caller), c: Container = Depends(get_container)) -> dict:
    uid = await _resolve_uid(c, ref)
    user = await c.store.get(f"users/{uid}") or {}
    against = await c.store.query(DocQuery("player_reports").filter("target_uid", "==", uid)
                                  .order("created_at_ms", "desc").take(50))
    by_user = await c.store.query(DocQuery("player_reports").filter("reporter_uid", "==", uid).take(50))
    history = await c.store.query(DocQuery("match_history").filter("participant_uids", "array_contains", uid)
                                  .order("completed_at_ms", "desc").take(20))
    safe = {k: user.get(k) for k in (
        "uid", "public_id", "username_display", "avatar_id", "frame_id", "status", "suspended_until_ms",
        "rename_required", "queue_restricted_until_ms", "ranked_restricted_until_ms", "mmr", "total_xp",
        "matches_completed", "ranked_matches_completed", "created_at_ms", "question_language", "ui_language")}
    await c.audit.record(actor=caller.uid, action="USER_VIEW", subject=f"user:{uid}")
    return {"schema_version": 1, "user": safe,
            "runtime": await c.store.get(f"user_runtime/{uid}"),
            "risk": await c.risk.get(uid), "sanctions": await c.sanctions.list_for(uid),
            "moderation_history": await c.sanctions.history(uid),
            "reports_against": [r.data for r in against],
            "reports_filed": len(by_user),
            "recent_matches": [{"match_id": h.id, "mode": h.data.get("mode"),
                                "completed_at_ms": h.data.get("completed_at_ms")} for h in history]}


@router.post("/users/{ref}/sanctions")
async def apply_sanction(ref: str, body: SanctionIn, caller: Caller = Depends(admin_caller),
                         c: Container = Depends(get_container)) -> dict:
    uid = await _resolve_uid(c, ref)
    return {"schema_version": 1, "sanction": await _apply(c, uid, body, caller.uid)}


@router.post("/sanctions/{sanction_id}/lift")
async def lift_sanction(sanction_id: str, body: LiftIn, caller: Caller = Depends(admin_caller),
                        c: Container = Depends(get_container)) -> dict:
    return {"schema_version": 1, "sanction": await c.sanctions.lift(sanction_id, actor=caller.uid,
                                                                    reason_code=body.reason_code)}


# ---------------------------------------------------------------------------------------------- risk


@router.get("/risk")
async def risk_queue(min_score: float = Query(default=0, ge=0), review_only: bool = True,
                     limit: int = Query(default=50, ge=1, le=200), caller: Caller = Depends(admin_caller),
                     c: Container = Depends(get_container)) -> dict:
    query = DocQuery("user_risk")
    if review_only:
        query = query.filter("review_required", "==", True)
    rows = await c.store.query(query.order("score", "desc").take(limit))
    items = []
    for row in rows:
        view = await c.risk.get(row.data["uid"])
        if view["score"] >= min_score:
            items.append({**view, "user": _user_card(await c.store.get(f"users/{row.data['uid']}"))})
    return {"schema_version": 1, "items": items}


@router.post("/users/{ref}/risk/review")
async def review_risk(ref: str, body: RiskReviewIn, caller: Caller = Depends(admin_caller),
                      c: Container = Depends(get_container)) -> dict:
    uid = await _resolve_uid(c, ref)
    return {"schema_version": 1, "risk": await c.risk.clear_review(uid, caller.uid, body.reason_code,
                                                                   body.reset_score)}
