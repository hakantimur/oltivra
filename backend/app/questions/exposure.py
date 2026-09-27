"""Global question-exposure history shared by Synova and Live Trivia (spec §10.2).

``user_recent_questions/{uid}`` keeps an ordered list (oldest -> newest) of the most recent 2,500 unique qids
actually shown to that user in any participating product.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.common.clock import Clock
from app.common.store.docstore import DocStore

HISTORY_LIMIT = 2500
EXCLUSION_LADDER = (2500, 1000, 300)


def append_unique(history: Sequence[int], shown: Iterable[int], limit: int = HISTORY_LIMIT) -> list[int]:
    """Move re-shown qids to the newest end, append new ones, keep the newest ``limit`` unique qids."""
    shown_list = list(dict.fromkeys(shown))
    shown_set = set(shown_list)
    kept = [q for q in history if q not in shown_set]
    merged = kept + shown_list
    return merged[-limit:]


@dataclass(frozen=True)
class ExposureUnion:
    """Recent-history union of every human participant (bots are ignored)."""

    histories: tuple[tuple[int, ...], ...]

    def excluded(self, window: int) -> set[int]:
        out: set[int] = set()
        for history in self.histories:
            out.update(history[-window:])
        return out

    def last_seen_rank(self, qid: int) -> int:
        """Higher = seen more recently by someone. -1 if nobody has seen it (preferred by LRU fallback)."""
        best = -1
        for history in self.histories:
            try:
                idx = history.index(qid)
            except ValueError:
                continue
            # Normalise so the newest entry of any history ranks HISTORY_LIMIT.
            best = max(best, HISTORY_LIMIT - (len(history) - 1 - idx))
        return best

    def tier(self, qid: int) -> int:
        """0 = outside last 2500 for everyone, 1 = outside last 1000, 2 = outside last 300, 3 = LRU fallback."""
        for tier, window in enumerate(EXCLUSION_LADDER):
            if all(qid not in history[-window:] for history in self.histories):
                return tier
        return len(EXCLUSION_LADDER)


class ExposureService:
    def __init__(self, store: DocStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    @staticmethod
    def path(uid: str) -> str:
        return f"user_recent_questions/{uid}"

    async def history(self, uid: str) -> list[int]:
        doc = await self._store.get(self.path(uid))
        return list(doc.get("qids", [])) if doc else []

    async def union(self, human_uids: Iterable[str]) -> ExposureUnion:
        uids = list(dict.fromkeys(human_uids))
        docs = await self._store.get_many([self.path(u) for u in uids]) if uids else []
        return ExposureUnion(tuple(tuple(d.get("qids", [])) if d else () for d in docs))

    def append_in_txn(self, txn, uid: str, shown: Sequence[int], existing: dict | None) -> None:
        """Write half of an idempotent settlement transaction (caller already read ``existing``)."""
        history = list(existing.get("qids", [])) if existing else []
        txn.set(self.path(uid), {
            "schema_version": 1,
            "uid": uid,
            "qids": append_unique(history, shown),
            "updated_at_ms": self._clock.now_ms(),
        })

    async def append(self, uid: str, shown: Sequence[int]) -> None:
        """Standalone transactional append (Synova solo sessions retry against the same record)."""
        if not shown:
            return

        def txn_fn(txn) -> None:
            existing = txn.get(self.path(uid))
            self.append_in_txn(txn, uid, shown, existing)

        await self._store.run_transaction(txn_fn)
