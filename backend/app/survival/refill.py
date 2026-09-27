"""Background Survival question refill (spec §26.2): another server-only batch when reserves run low."""

from __future__ import annotations

import logging
from typing import Any

from app.matches.model import humans
from app.matches.service import root_path
from app.questions.models import Difficulty
from app.questions.selector import InsufficientInventory
from app.survival import rules

log = logging.getLogger("oltivra.survival")

REFILL_TARGETS = {Difficulty.EASY: 4, Difficulty.MEDIUM: 6, Difficulty.HARD: 6}


class SurvivalRefill:
    def __init__(self, container) -> None:
        self._c = container

    async def refill(self, match_id: str, shard_id: str, data: dict[str, Any]) -> None:
        c = self._c
        batch = int(data.get("batch", 1))
        state = await c.live.get(shard_id, f"{root_path(match_id)}/authoritative")
        if not state:
            return
        pools = (state.get("plan") or {}).get("pools") or {}
        exclude = set(state.get("used_gids") or []) | {i["gid"] for items in pools.values() for i in items or []}
        uids = [p["uid"] for p in humans(state).values()]
        try:
            items = await c.question_plans.survival_plan(state["language"], uids, seed=f"{match_id}:refill:{batch}",
                                                         exclude_gids=exclude, targets=REFILL_TARGETS,
                                                         category_id=(state.get("plan") or {}).get("category_id"))
        except InsufficientInventory:
            log.warning("survival_refill_exhausted", extra={"match_id": match_id})
            items = {}
        now = c.clock.now_ms()
        await c.matches.mutate(match_id, shard_id, lambda s: rules.add_pool_items(s, batch, items, now))
