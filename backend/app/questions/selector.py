"""Pure question selection over manifest entries (spec §3.4, §3.5, §10.2, §26).

Priority: never repeat a group in a match > exposure fallback ladder > category diversity.
Diversity is only applied *within* the best available exposure tier, so it never weakens exposure
restrictions (spec §3.5 last bullet).
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Sequence

from app.manifests.manifest import ManifestEntry
from app.questions.exposure import EXCLUSION_LADDER, ExposureUnion
from app.questions.models import Difficulty

QUICK_NORMAL_ORDER: tuple[Difficulty, ...] = (
    Difficulty.EASY, Difficulty.EASY,
    Difficulty.MEDIUM, Difficulty.MEDIUM, Difficulty.MEDIUM, Difficulty.MEDIUM, Difficulty.MEDIUM,
    Difficulty.HARD, Difficulty.HARD, Difficulty.HARD,
)
QUICK_RESERVE_ORDER: tuple[Difficulty, ...] = (
    Difficulty.MEDIUM, Difficulty.HARD, Difficulty.HARD, Difficulty.HARD, Difficulty.HARD,
)
SURVIVAL_POOL_TARGET: dict[Difficulty, int] = {Difficulty.EASY: 14, Difficulty.MEDIUM: 14, Difficulty.HARD: 12}
QUICK_MAX_PER_CATEGORY = 2


class InsufficientInventory(Exception):
    def __init__(self, difficulty: Difficulty) -> None:
        super().__init__(f"no eligible {difficulty} question left")
        self.difficulty = difficulty


class _Tiering:
    def __init__(self, union: ExposureUnion) -> None:
        self.union = union
        self.windows = [union.excluded(w) for w in EXCLUSION_LADDER]

    def tier(self, qid: int) -> int:
        for index, excluded in enumerate(self.windows):
            if qid not in excluded:
                return index
        return len(self.windows)


def _pick(
    candidates: list[ManifestEntry],
    tiering: _Tiering,
    rng: random.Random,
    category_counts: Counter,
    previous_sub: str | None,
    max_per_category: int,
    prefer_new_categories: bool,
) -> ManifestEntry | None:
    if not candidates:
        return None
    by_tier: dict[int, list[ManifestEntry]] = {}
    for entry in candidates:
        by_tier.setdefault(tiering.tier(entry.qid), []).append(entry)
    best_tier = min(by_tier)
    pool = by_tier[best_tier]
    if best_tier == len(EXCLUSION_LADDER):
        # Least-recently-seen fallback: keep only the least recently seen ranks.
        ranked = sorted(pool, key=lambda e: tiering.union.last_seen_rank(e.qid))
        floor = tiering.union.last_seen_rank(ranked[0].qid)
        pool = [e for e in ranked if tiering.union.last_seen_rank(e.qid) <= floor + 50]

    diverse = [e for e in pool if category_counts[e.cat] < max_per_category and e.sub != previous_sub]
    if prefer_new_categories:
        fresh = [e for e in diverse if category_counts[e.cat] == 0]
        if fresh:
            return rng.choice(fresh)
    if diverse:
        return rng.choice(diverse)
    no_repeat_sub = [e for e in pool if e.sub != previous_sub]
    return rng.choice(no_repeat_sub or pool)


def select_sequence(
    order: Sequence[Difficulty],
    pools: dict[Difficulty, list[ManifestEntry]],
    union: ExposureUnion,
    rng: random.Random,
    used_gids: set[str] | None = None,
    max_per_category: int = QUICK_MAX_PER_CATEGORY,
    prefer_new_categories: bool = True,
    previous_sub: str | None = None,
    category_counts: Counter | None = None,
) -> list[ManifestEntry]:
    used = set(used_gids or ())
    counts: Counter = category_counts if category_counts is not None else Counter()
    tiering = _Tiering(union)
    chosen: list[ManifestEntry] = []
    for difficulty in order:
        candidates = [e for e in pools.get(difficulty, []) if e.gid not in used]
        pick = _pick(candidates, tiering, rng, counts, previous_sub, max_per_category, prefer_new_categories)
        if pick is None:
            raise InsufficientInventory(difficulty)
        chosen.append(pick)
        used.add(pick.gid)
        counts[pick.cat] += 1
        previous_sub = pick.sub
    return chosen


def select_quick(pools: dict[Difficulty, list[ManifestEntry]], union: ExposureUnion, rng: random.Random,
                 used_gids: set[str] | None = None) -> tuple[list[ManifestEntry], list[ManifestEntry]]:
    """Ten normal questions in Easy/Medium/Hard order plus five reserves (spec §26.1)."""
    counts: Counter = Counter()
    normal = select_sequence(QUICK_NORMAL_ORDER, pools, union, rng, used_gids, category_counts=counts)
    used = set(used_gids or ()) | {e.gid for e in normal}
    reserves = select_sequence(QUICK_RESERVE_ORDER, pools, union, rng, used, max_per_category=10**6,
                               prefer_new_categories=False, previous_sub=normal[-1].sub)
    return normal, reserves


def select_survival(pools: dict[Difficulty, list[ManifestEntry]], union: ExposureUnion, rng: random.Random,
                    targets: dict[Difficulty, int] | None = None,
                    used_gids: set[str] | None = None) -> dict[Difficulty, list[ManifestEntry]]:
    """At least 30 candidates plus 10 reserves spread over difficulties (spec §26.2)."""
    targets = targets or SURVIVAL_POOL_TARGET
    used = set(used_gids or ())
    out: dict[Difficulty, list[ManifestEntry]] = {}
    for difficulty, count in targets.items():
        available = len([e for e in pools.get(difficulty, []) if e.gid not in used])
        take = min(count, available)
        if take == 0:
            out[difficulty] = []
            continue
        per_cat = max(2, -(-take // 9) + 1)
        picks = select_sequence([difficulty] * take, pools, union, rng, used, max_per_category=per_cat)
        used |= {e.gid for e in picks}
        out[difficulty] = picks
    return out
