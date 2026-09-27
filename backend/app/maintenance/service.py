"""Low-frequency maintenance jobs (Cloud Scheduler -> OIDC-authenticated internal routes, spec §20.6, §27.7).

Every job is idempotent and bounded, so a duplicate or overlapping scheduler invocation is harmless.
"""

from __future__ import annotations

import logging
from typing import Any

from app.common.clock import iso_week_id, next_iso_week_start_ms
from app.common.errors import ApiError
from app.common.store.docstore import Query
from app.missions.service import period_ids
from app.notifications.service import NotificationKind
from app.questions.models import QuestionStatus

log = logging.getLogger("oltivra.maintenance")

DAY_MS = 86_400_000
PREPARING_STALE_MS = 2 * 60_000
LIVE_STALE_MS = {"QUICK": 15 * 60_000, "SURVIVAL": 45 * 60_000}
PENDING_SETTLEMENT_STALE_MS = 60_000
STAT_MODES = ("QUICK", "SURVIVAL", "SYNOVA")


class MaintenanceService:
    def __init__(self, container) -> None:
        self._c = container

    async def expire_tickets(self) -> dict[str, Any]:
        return {"expired": await self._c.matchmaking.sweep_expired()}

    async def expire_sanctions(self) -> dict[str, Any]:
        return {"users_refreshed": await self._c.sanctions.expire_due()}

    async def rebuild_manifests(self) -> dict[str, Any]:
        c = self._c
        config = await c.config.get()
        languages = sorted(set(config.features.competitive_languages) | set(config.features.ui_languages))
        counts = await c.manifest_builder.build_all(languages)
        c.manifest_cache.invalidate()
        return {"manifests": len(counts), "entries": sum(counts.values())}

    async def reconcile_purchases(self) -> dict[str, Any]:
        return {"changed": await self._c.purchases.reconcile_google()}

    async def release_usernames(self, limit: int = 500) -> dict[str, Any]:
        """Release expired username reservations (renames and deleted accounts after 30 days, spec §30.1)."""
        c = self._c
        now = c.clock.now_ms()
        rows = await c.store.query(Query("username_registry").filter("state", "==", "RESERVED")
                                   .filter("reserved_until_ms", "<=", now).take(limit))
        for row in rows:
            await c.store.delete(row.path)
        return {"released": len(rows)}

    async def aggregate_question_stats(self, limit: int = 500) -> dict[str, Any]:
        """Fold sharded human counters into summaries, resuming from a cursor across runs."""
        c = self._c
        config = await c.config.get()
        languages = sorted(set(config.features.competitive_languages) | set(config.features.ui_languages))
        cursor_doc = await c.store.get("maintenance_state/question_stats") or {}
        after = int(cursor_doc.get("after_qid", -1))
        rows = await c.store.query(Query("question_groups").filter("qid", ">", after).order("qid", "asc")
                                   .take(limit))
        rows = [r for r in rows if r.data.get("status") in (QuestionStatus.ACTIVE.value,
                                                             QuestionStatus.QUARANTINED.value)]
        keys = 0
        for row in rows:
            for language in row.data.get("languages") or languages:
                for mode in STAT_MODES:
                    totals = await c.question_stats.aggregate(f"{row.id}_{row.data['version']}_{language}_{mode}")
                    keys += int(any(totals.values()))
        last = rows[-1].data["qid"] if rows else -1
        exhausted = len(rows) < limit
        await c.store.set("maintenance_state/question_stats", {
            "schema_version": 1, "after_qid": -1 if exhausted else last, "updated_at_ms": c.clock.now_ms()})
        return {"groups": len(rows), "keys_with_data": keys, "wrapped": exhausted}

    async def sweep_stale_matches(self, limit: int = 200) -> dict[str, Any]:
        """Rediscover matches whose tasks were lost (spec §20.4 recovery callers)."""
        from app.matches.service import root_path

        c = self._c
        now = c.clock.now_ms()
        out = {"resolved": 0, "settlement_rescheduled": 0, "aborted": 0}
        preparing = await c.store.query(Query("match_index").filter("state", "==", "PREPARING")
                                        .filter("created_at_ms", "<=", now - PREPARING_STALE_MS).take(limit))
        for row in preparing:
            shard = row.data["rtdb_shard_id"]
            if await c.live.get(shard, f"{root_path(row.id)}/authoritative"):
                await c.store.update(row.path, {"state": "LIVE", "started_at_ms": row.data["created_at_ms"]})
                continue
            await c.settlement.abort_unstarted(row.id, "stale_preparing")
            out["aborted"] += 1
        live = await c.store.query(Query("match_index").filter("state", "==", "LIVE").take(limit))
        for row in live:
            started = int(row.data.get("started_at_ms") or row.data.get("created_at_ms") or now)
            if now - started < LIVE_STALE_MS.get(row.data.get("mode"), LIVE_STALE_MS["SURVIVAL"]):
                continue
            try:
                await c.matches.resolve(row.id, row.data["rtdb_shard_id"], "MAINTENANCE_SWEEP")
                out["resolved"] += 1
            except ApiError as exc:
                log.warning("stale_match_resolve_failed", extra={"match_id": row.id, "code": exc.code.value})
        for state in ("FINISHED_PENDING_SETTLEMENT", "CANCELLED_PENDING"):
            pending = await c.store.query(Query("match_index").filter("state", "==", state)
                                          .filter("finished_at_ms", "<=", now - PENDING_SETTLEMENT_STALE_MS)
                                          .take(limit))
            for row in pending:
                await c.settlement.ensure_scheduled(row.id, row.data["rtdb_shard_id"])
                out["settlement_rescheduled"] += 1
        return out

    async def leaderboard_ending_reminders(self, limit: int = 2000) -> dict[str, Any]:
        """During the final day of the ISO week, remind players who have ranked progress this week."""
        c = self._c
        now = c.clock.now_ms()
        if next_iso_week_start_ms(now) - now > DAY_MS:
            return {"sent": 0, "skipped": "not_final_day"}
        rows = await c.store.query(Query("weekly_user_stats").filter("week_id", "==", iso_week_id(now)).take(limit))
        sent = 0
        for row in rows:
            sent += await c.notifications.notify(row.data["uid"], NotificationKind.LEADERBOARD_ENDING)
        return {"sent": sent, "candidates": len(rows)}

    async def mission_reminders(self, limit: int = 2000) -> dict[str, Any]:
        """Remind players with unfinished or unclaimed daily missions (spacing enforced per recipient)."""
        c = self._c
        now = c.clock.now_ms()
        rows = await c.store.query(Query("user_missions").filter("period_id", "==", period_ids(now)["DAILY"])
                                   .take(limit))
        sent = 0
        for row in rows:
            missions = row.data.get("missions") or []
            if any(not m["completed"] or not m["claimed"] for m in missions):
                sent += await c.notifications.notify(row.data["uid"], NotificationKind.MISSION_REMINDER)
        return {"sent": sent, "candidates": len(rows)}


JOBS = {
    "expire-tickets": MaintenanceService.expire_tickets,
    "expire-sanctions": MaintenanceService.expire_sanctions,
    "rebuild-manifests": MaintenanceService.rebuild_manifests,
    "reconcile-purchases": MaintenanceService.reconcile_purchases,
    "release-usernames": MaintenanceService.release_usernames,
    "aggregate-question-stats": MaintenanceService.aggregate_question_stats,
    "sweep-stale-matches": MaintenanceService.sweep_stale_matches,
    "leaderboard-ending-reminders": MaintenanceService.leaderboard_ending_reminders,
    "mission-reminders": MaintenanceService.mission_reminders,
}
