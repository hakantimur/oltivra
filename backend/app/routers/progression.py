"""Progression endpoints (spec §27.6): missions, weekly leaderboard, league, category stats, match history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.common.api import Caller, get_container, player, run_mutation
from app.common.errors import ApiError, ErrorCode
from app.common.store.docstore import Query as DocQuery
from app.container import Container
from app.progression.service import category_path
from app.questions.taxonomy import CATEGORIES
from app.ranking.leagues import League

router = APIRouter(prefix="/v1")


class MutationBody(BaseModel):
    request_id: str


@router.get("/missions/daily")
async def daily_missions(caller: Caller = Depends(player), c: Container = Depends(get_container)) -> dict:
    return await c.missions.current(caller.uid, "DAILY")


@router.get("/missions/weekly")
async def weekly_missions(caller: Caller = Depends(player), c: Container = Depends(get_container)) -> dict:
    return await c.missions.current(caller.uid, "WEEKLY")


@router.post("/missions/{mission_id}/claim")
async def claim_mission(mission_id: str, body: MutationBody, request: Request, caller: Caller = Depends(player),
                        c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        return await c.missions.claim(caller.uid, mission_id)

    return await run_mutation(c, request, caller, f"missions.claim.{mission_id}", body.model_dump(), handler)


@router.get("/leaderboards/weekly")
async def weekly_leaderboard(week_id: str | None = Query(default=None, max_length=10),
                             league: str | None = Query(default=None, max_length=16),
                             limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0,
                                                                                               le=10_000),
                             caller: Caller = Depends(player), c: Container = Depends(get_container)) -> dict:
    if league is not None and league not in {lg.value for lg in League}:
        raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "unknown_league"})
    return await c.leaderboard.weekly(caller.uid, week_id=week_id, league=league, limit=limit, offset=offset)


@router.get("/league")
async def league(caller: Caller = Depends(player), c: Container = Depends(get_container)) -> dict:
    """This week's league group: tier, standings with promotion/relegation zones and last week's result.
    Raw MMR never leaves the server (spec §7.3)."""
    view = await c.leagues.view(caller.uid, c.clock.now_ms())
    view["ranked_matches_completed"] = int((caller.user or {}).get("ranked_matches_completed", 0))
    return view


@router.get("/category-stats")
async def category_stats(caller: Caller = Depends(player), c: Container = Depends(get_container)) -> dict:
    doc = await c.store.get(category_path(caller.uid)) or {}
    stats = doc.get("categories") or {}
    items = []
    for category in CATEGORIES:
        row = stats.get(category.id) or {}
        answered, correct = int(row.get("answered", 0)), int(row.get("correct", 0))
        items.append({
            "category_id": category.id, "names": category.names, "icon": category.icon,
            "seen": int(row.get("seen", 0)), "answered": answered, "correct": correct,
            "accuracy": round(correct / answered, 4) if answered else None,
            "avg_correct_ms": round(int(row.get("sum_correct_ms", 0)) / correct) if correct else None,
        })
    return {"schema_version": 1, "categories": items}


@router.get("/match-history")
async def match_history(limit: int = Query(default=20, ge=1, le=50), caller: Caller = Depends(player),
                        c: Container = Depends(get_container)) -> dict:
    """Own recent matches. Never reveals which opponents were computer-controlled (D3)."""
    rows = await c.store.query(DocQuery("match_history").filter("participant_uids", "array_contains", caller.uid)
                               .order("completed_at_ms", "desc").take(limit))
    items = []
    for row in rows:
        data = row.data
        me = next((p for p in data.get("participants", []) if p.get("uid_or_bot_id") == caller.uid), {})
        items.append({
            "match_id": data["match_id"], "mode": data["mode"], "completed_at_ms": data["completed_at_ms"],
            "cancelled": bool(data.get("cancelled")), "ranked": bool(data.get("ranked_eligible")),
            "place": me.get("place"), "score": me.get("normal_score"), "xp_awarded": me.get("xp_awarded", 0),
            "players": len(data.get("participants", [])),
        })
    return {"schema_version": 1, "matches": items}
