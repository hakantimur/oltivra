"""Language activation gate (spec §12.2): inventory thresholds plus selection simulation."""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass

from app.manifests.manifest import ManifestCache
from app.questions.exposure import ExposureUnion
from app.questions.models import Difficulty
from app.questions.selector import InsufficientInventory, select_quick
from app.questions.taxonomy import CATEGORY_IDS

SOFT_LAUNCH = {"total": 6000, "per_band": {"EASY": 1500, "MEDIUM": 1500, "HARD": 1500}, "simulation": 0.99}
FULL_SCALE = {"total": 12000, "per_band": {"EASY": 2500, "MEDIUM": 4000, "HARD": 2500}, "simulation": 0.995}


@dataclass
class GateReport:
    language: str
    total_groups: int
    per_difficulty: dict[str, int]
    categories_represented: int
    simulation_trials: int
    simulation_success_rate: float
    soft_launch_ready: bool
    full_scale_ready: bool

    def as_dict(self) -> dict:
        return asdict(self)


def _ready(thresholds: dict, total: int, per: dict[str, int], categories: int, rate: float) -> bool:
    return (total >= thresholds["total"] and all(per[k] >= v for k, v in thresholds["per_band"].items())
            and categories == len(CATEGORY_IDS) and rate >= thresholds["simulation"])


async def language_gate_report(manifests: ManifestCache, language: str, trials: int = 1000,
                               seed: int = 7) -> GateReport:
    pools = {d: await manifests.get(language, "QUICK", d.value) for d in Difficulty}
    per = {d.value: len(pools[d]) for d in Difficulty}
    groups = {e.gid for entries in pools.values() for e in entries}
    categories = len({e.cat for entries in pools.values() for e in entries})
    all_qids = [e.qid for entries in pools.values() for e in entries]
    rng = random.Random(seed)
    successes = 0
    for _ in range(trials):
        # Realistic four-player recent-history unions: each player has seen a random slice of the pool.
        histories = tuple(tuple(rng.sample(all_qids, min(len(all_qids), rng.randint(0, 2500))))
                          for _ in range(4)) if all_qids else ((),)
        union = ExposureUnion(histories)
        try:
            normal, reserves = select_quick(pools, union, random.Random(rng.random()))
        except InsufficientInventory:
            continue
        excluded = union.excluded(2500)
        if all(e.qid not in excluded for e in normal + reserves):
            successes += 1
    rate = successes / trials if trials else 0.0
    total = len(groups)
    soft = _ready(SOFT_LAUNCH, total, per, categories, rate)
    full = _ready(FULL_SCALE, total, per, categories, rate)
    return GateReport(language, total, per, categories, trials, rate, soft, full)
