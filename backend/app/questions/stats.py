"""Sharded human question statistics (spec §10.3, §33.2). Bots never write here."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from app.common.store.docstore import DocStore, Increment, Query

STAT_SHARDS = 32
FIELDS = ("shown", "attempted", "correct", "wrong", "no_answer", "censored_by_early_quick_winner",
          "sum_response_ms", "report_count")


@dataclass
class StatIntent:
    gid: str
    version: int
    language: str
    mode: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.gid}_{self.version}_{self.language}_{self.mode}"


def shard_path(key: str, shard: int) -> str:
    return f"question_stats_shards/{key}/shards/{shard}"


class QuestionStatsService:
    def __init__(self, store: DocStore, rng: random.Random | None = None) -> None:
        self._store = store
        self._rng = rng or random.Random()

    async def apply(self, intents: list[StatIntent]) -> None:
        for intent in intents:
            counts = {k: Increment(v) for k, v in intent.counts.items() if v and k in FIELDS}
            if not counts:
                continue
            path = shard_path(intent.key, self._rng.randrange(STAT_SHARDS))
            await self._store.set(path, {"schema_version": 1, **counts}, merge=True)

    async def aggregate(self, key: str) -> dict[str, int]:
        rows = await self._store.query(Query(f"question_stats_shards/{key}/shards"))
        totals = {f: 0 for f in FIELDS}
        for row in rows:
            for f in FIELDS:
                totals[f] += int(row.data.get(f, 0))
        await self._store.set(f"question_stats_summaries/{key}", {"schema_version": 1, **totals})
        return totals
