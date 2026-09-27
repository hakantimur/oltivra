"""Pool-health dashboard and language activation gate (spec §12.2).

Selection simulation runs synthetic four-player rosters with realistic recent-history unions and checks that
normal + reserve questions can be chosen under language, status, diversity and exposure constraints.
"""

from __future__ import annotations

import random
from collections import Counter
from typing import Any

from app.common.store.docstore import Query
from app.questions.exposure import ExposureUnion
from app.questions.models import Difficulty
from app.questions.selector import InsufficientInventory, select_quick, select_survival
from app.questions.taxonomy import CATEGORIES

SOFT_LAUNCH = {"total": 6000, "per_difficulty": {"EASY": 1500, "MEDIUM": 1500, "HARD": 1500}, "simulation": 0.99}
FULL_SCALE = {"total": 12000, "per_difficulty": {"EASY": 2500, "MEDIUM": 4000, "HARD": 2500}, "simulation": 0.995}
HISTORY_PER_PLAYER = 400


class PoolHealthService:
    def __init__(self, container) -> None:
        self._c = container

    async def _pools(self, language: str, mode: str):
        return {d: await self._c.manifest_cache.get(language, mode, d.value) for d in Difficulty}

    def simulate(self, pools, mode: str, trials: int, seed: int = 7) -> float:
        rng = random.Random(seed)
        all_qids = [e.qid for entries in pools.values() for e in entries]
        if not all_qids:
            return 0.0
        ok = 0
        for _ in range(trials):
            histories = tuple(tuple(rng.sample(all_qids, min(len(all_qids), rng.randint(0, HISTORY_PER_PLAYER))))
                              for _ in range(4))
            union = ExposureUnion(histories)
            try:
                if mode == "QUICK":
                    select_quick(pools, union, random.Random(rng.random()))
                else:
                    picks = select_survival(pools, union, random.Random(rng.random()))
                    if sum(len(v) for v in picks.values()) < 40:
                        raise InsufficientInventory(Difficulty.EASY)
                ok += 1
            except InsufficientInventory:
                continue
        return ok / trials

    async def report(self, language: str, trials: int = 200) -> dict[str, Any]:
        quick = await self._pools(language, "QUICK")
        survival = await self._pools(language, "SURVIVAL")
        per_difficulty = {d.value: len(entries) for d, entries in quick.items()}
        total = sum(per_difficulty.values())
        coverage: dict[str, dict[str, int]] = {}
        for difficulty, entries in quick.items():
            counts = Counter(e.cat for e in entries)
            coverage[difficulty.value] = {c.id: counts.get(c.id, 0) for c in CATEGORIES}
        all_categories = all(any(coverage[d][c.id] for d in coverage) for c in CATEGORIES)
        every_band = all(all(coverage[d][c.id] for c in CATEGORIES) for d in coverage)
        quick_sim = self.simulate(quick, "QUICK", trials)
        survival_sim = self.simulate(survival, "SURVIVAL", max(20, trials // 5))
        counters = [r.data for r in await self._c.store.query(Query("question_report_counters"))]
        config = await self._c.config.get()

        def gate(spec: dict[str, Any], categories_ok: bool) -> dict[str, Any]:
            checks = {
                "total_active_groups": total >= spec["total"],
                "per_difficulty": all(per_difficulty.get(d, 0) >= n for d, n in spec["per_difficulty"].items()),
                "all_categories": categories_ok,
                "selection_simulation": quick_sim >= spec["simulation"],
            }
            return {"passed": all(checks.values()), "checks": checks, "requirements": spec}

        return {
            "schema_version": 1,
            "language": language,
            "active_competitive_groups": total,
            "per_difficulty": per_difficulty,
            "survival_per_difficulty": {d.value: len(e) for d, e in survival.items()},
            "category_coverage": coverage,
            "simulation": {"quick_success_rate": round(quick_sim, 4), "survival_success_rate": round(survival_sim, 4),
                           "trials": trials},
            "reports": {"questions_with_reports": len(counters),
                        "quarantine_threshold_reporters": config.moderation.question_quarantine_min_reporters,
                        "quarantine_rate": config.moderation.question_quarantine_rate},
            "language_gate": {"soft_launch": gate(SOFT_LAUNCH, all_categories),
                              "full_scale": gate(FULL_SCALE, every_band)},
            "competitive_enabled": language in config.features.competitive_languages,
        }
