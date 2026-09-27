"""Daily and weekly missions (spec §7.8): deterministic per UID/period, server-authoritative, idempotent claims.

Progress comes only from settled, non-cancelled matches; a rewarded XP multiplier never doubles progress.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from app.common.clock import iso_week_id, next_iso_week_start_ms, next_utc_midnight_ms, utc_date_id
from app.common.errors import ApiError, ErrorCode
from app.common.keys import Keyring
from app.common.server_config import GameConfig

DAILY_COUNT = 3


@dataclass(frozen=True)
class Template:
    id: str
    metric: str
    target: int


DAILY_TEMPLATES: tuple[Template, ...] = (
    Template("play_quick_3", "quick_played", 3),
    Template("win_quick_questions_5", "quick_question_wins", 5),
    Template("answer_correct_10", "correct_answers", 10),
    Template("play_survival_1", "survival_played", 1),
    Template("earn_quick_points_100", "quick_points", 100),
    Template("send_reactions_5", "reactions_sent", 5),
    Template("win_ranked_quick_1", "quick_ranked_wins", 1),
    Template("play_matches_3", "matches_played", 3),
)
WEEKLY_TEMPLATES: tuple[Template, ...] = (
    Template("play_quick_15", "quick_played", 15),
    Template("win_ranked_quick_3", "quick_ranked_wins", 3),
    Template("survival_top3_ranked_1", "survival_ranked_top3", 1),
    Template("answer_correct_60", "correct_answers", 60),
    Template("earn_quick_points_500", "quick_points", 500),
    Template("play_survival_5", "survival_played", 5),
    Template("survive_rounds_25", "survival_rounds", 25),
    Template("send_reactions_20", "reactions_sent", 20),
)
_BY_ID = {t.id: t for t in DAILY_TEMPLATES + WEEKLY_TEMPLATES}


def period_ids(now_ms: int) -> dict[str, str]:
    return {"DAILY": f"D{utc_date_id(now_ms)}", "WEEKLY": f"W{iso_week_id(now_ms)}"}


def mission_path(uid: str, period_id: str) -> str:
    return f"user_missions/{uid}_{period_id}"


def generate(keys: Keyring, uid: str, period: str, period_id: str, now_ms: int, config: GameConfig) -> dict[str, Any]:
    templates = DAILY_TEMPLATES if period == "DAILY" else WEEKLY_TEMPLATES
    count = DAILY_COUNT if period == "DAILY" else max(3, min(5, config.economy.weekly_mission_count))
    xp = config.economy.daily_mission_xp if period == "DAILY" else config.economy.weekly_mission_xp
    rng = random.Random(int.from_bytes(keys.mission.digest(f"{uid}:{period_id}")[:8], "big"))
    chosen = rng.sample(list(templates), count)
    ends = next_utc_midnight_ms(now_ms) if period == "DAILY" else next_iso_week_start_ms(now_ms)
    return {
        "schema_version": 1, "uid": uid, "period": period, "period_id": period_id, "ends_at_ms": ends,
        "missions": [{"mission_id": f"{period_id}.{i}", "template_id": t.id, "metric": t.metric, "target": t.target,
                      "progress": 0, "completed": False, "claimed": False, "xp": xp} for i, t in enumerate(chosen)],
        "created_at_ms": now_ms,
    }


def apply_metrics(doc: dict[str, Any], metrics: dict[str, int], now_ms: int) -> list[str]:
    """Advance progress in place; returns mission IDs completed by this update."""
    completed: list[str] = []
    for mission in doc["missions"]:
        if mission["completed"]:
            continue
        gained = int(metrics.get(mission["metric"], 0))
        if gained <= 0:
            continue
        mission["progress"] = min(mission["target"], mission["progress"] + gained)
        if mission["progress"] >= mission["target"]:
            mission["completed"] = True
            mission["completed_at_ms"] = now_ms
            completed.append(mission["mission_id"])
    doc["updated_at_ms"] = now_ms
    return completed


def view(doc: dict[str, Any], ui_language: str = "en") -> dict[str, Any]:
    return {
        "schema_version": 1, "period": doc["period"], "period_id": doc["period_id"], "ends_at_ms": doc["ends_at_ms"],
        "missions": [{k: m[k] for k in ("mission_id", "template_id", "target", "progress", "completed", "claimed",
                                        "xp")} for m in doc["missions"]],
    }


class MissionService:
    def __init__(self, container) -> None:
        self._c = container

    async def current(self, uid: str, period: str) -> dict[str, Any]:
        c = self._c
        now = c.clock.now_ms()
        period_id = period_ids(now)[period]
        doc = await c.store.get(mission_path(uid, period_id))
        if not doc:
            config = await c.config.get()
            fresh = generate(c.keys, uid, period, period_id, now, config)

            def txn_fn(txn) -> dict[str, Any]:
                existing = txn.get(mission_path(uid, period_id))
                if existing:
                    return existing
                txn.set(mission_path(uid, period_id), fresh)
                return fresh

            doc = await c.store.run_transaction(txn_fn)
        return view(doc)

    async def claim(self, uid: str, mission_id: str) -> dict[str, Any]:
        c = self._c
        period_id = mission_id.split(".")[0]
        if not period_id or period_id[0] not in "DW":
            raise ApiError(ErrorCode.NOT_FOUND)
        now = c.clock.now_ms()
        from app.profiles.service import user_path
        from app.ranking.levels import level_for_xp

        def txn_fn(txn) -> dict[str, Any]:
            doc, user = txn.get_many([mission_path(uid, period_id), user_path(uid)])
            mission = next((m for m in (doc or {}).get("missions", []) if m["mission_id"] == mission_id), None)
            if not mission or not user:
                raise ApiError(ErrorCode.NOT_FOUND)
            if mission["claimed"]:
                return {"claimed": True, "xp_awarded": 0, "replay": True, "total_xp": user.get("total_xp", 0)}
            if not mission["completed"]:
                raise ApiError(ErrorCode.MISSION_NOT_COMPLETE)
            mission["claimed"] = True
            mission["claimed_at_ms"] = now
            total = int(user.get("total_xp", 0)) + int(mission["xp"])
            updated = {**user, "total_xp": total}
            txn.set(mission_path(uid, period_id), doc)
            txn.update(user_path(uid), {"total_xp": total})
            txn.set(f"public_profiles/{user['public_id']}", c.profiles.public_profile(updated))
            return {"claimed": True, "xp_awarded": mission["xp"], "replay": False, "total_xp": total,
                    "level": level_for_xp(total)}

        return {"schema_version": 1, "mission_id": mission_id, **await c.store.run_transaction(txn_fn)}


