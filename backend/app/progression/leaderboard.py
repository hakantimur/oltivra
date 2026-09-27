"""Weekly leaderboard (spec §7.6, §33.3): one document per UID/week, indexed pagination, no global document.

Order: ranked_weekly_xp desc, quick_ranked_wins desc, survival_ranked_crowns desc, tie_break_hash asc.
"""

from __future__ import annotations

from typing import Any

from app.common.clock import iso_week_id
from app.common.store.docstore import Query
from app.progression.service import weekly_path

MAX_PAGE = 100
RANK_SCAN_LIMIT = 5000


def _sort_key(doc: dict[str, Any]) -> tuple:
    return (-int(doc.get("ranked_weekly_xp", 0)), -int(doc.get("quick_ranked_wins", 0)),
            -int(doc.get("survival_ranked_crowns", 0)), doc.get("tie_break_hash", ""))


def _entry(doc: dict[str, Any], rank: int) -> dict[str, Any]:
    return {"rank": rank, "public_id": doc.get("public_id"), "username": doc.get("username"),
            "avatar_id": doc.get("avatar_id"), "frame_id": doc.get("frame_id", "frame_none"),
            "league": doc.get("league"), "ranked_weekly_xp": int(doc.get("ranked_weekly_xp", 0)),
            "quick_ranked_wins": int(doc.get("quick_ranked_wins", 0)),
            "survival_ranked_crowns": int(doc.get("survival_ranked_crowns", 0))}


class LeaderboardService:
    def __init__(self, container) -> None:
        self._c = container

    def _query(self, week_id: str, league: str | None) -> Query:
        query = Query("weekly_user_stats").filter("week_id", "==", week_id)
        if league:
            query = query.filter("league", "==", league)
        return (query.order("ranked_weekly_xp", "desc").order("quick_ranked_wins", "desc")
                .order("survival_ranked_crowns", "desc").order("tie_break_hash", "asc"))

    async def weekly(self, uid: str, *, week_id: str | None = None, league: str | None = None, limit: int = 50,
                     offset: int = 0) -> dict[str, Any]:
        c = self._c
        week = week_id or iso_week_id(c.clock.now_ms())
        limit = max(1, min(limit, MAX_PAGE))
        rows = await c.store.query(self._query(week, league).take(limit, max(0, offset)))
        entries = [_entry(r.data, offset + i + 1) for i, r in enumerate(rows)]
        mine = await c.store.get(weekly_path(week, uid))
        me = None
        if mine and (not league or mine.get("league") == league):
            ahead_query = Query("weekly_user_stats").filter("week_id", "==", week).filter(
                "ranked_weekly_xp", ">=", int(mine.get("ranked_weekly_xp", 0)))
            if league:
                ahead_query = ahead_query.filter("league", "==", league)
            candidates = await c.store.query(ahead_query.take(RANK_SCAN_LIMIT))
            key = _sort_key(mine)
            rank = 1 + sum(1 for r in candidates if _sort_key(r.data) < key)
            me = _entry(mine, rank)
        return {"schema_version": 1, "week_id": week, "league": league, "entries": entries, "me": me,
                "next_offset": offset + len(entries) if len(entries) == limit else None}
