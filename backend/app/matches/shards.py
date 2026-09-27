"""RTDB shard ring assignment and admission control (spec §14.1, §36.2)."""

from __future__ import annotations

from app.common.errors import ApiError, ErrorCode
from app.common.keys import Keyring
from app.common.store.docstore import DocStore, Increment


def shard_for(keys: Keyring, match_id: str, shard_ids: list[str]) -> str:
    """``shard_index = first_uint32(HMAC(match_shard_key, match_id)) mod N``; a match never moves."""
    return shard_ids[keys.shard.first_uint32(match_id) % len(shard_ids)]


def health_path(shard_id: str) -> str:
    return f"shard_health/{shard_id}"


class ShardAdmission:
    """Tracks active rooms per shard; new matches are refused before an overloaded shard hurts fairness."""

    def __init__(self, store: DocStore) -> None:
        self._store = store

    async def check(self, shard_id: str, max_active_rooms: int) -> None:
        doc = await self._store.get(health_path(shard_id)) or {}
        if doc.get("unhealthy") or int(doc.get("active_rooms", 0)) >= max_active_rooms:
            raise ApiError(ErrorCode.CAPACITY_UNAVAILABLE, retry_after_s=5, detail={"reason": "shard_capacity"})

    @staticmethod
    def room_opened_in_txn(txn, shard_id: str, now_ms: int) -> None:
        txn.set(health_path(shard_id), {"shard_id": shard_id, "active_rooms": Increment(1), "updated_at_ms": now_ms},
                merge=True)

    async def room_closed(self, shard_id: str, now_ms: int) -> None:
        await self._store.set(health_path(shard_id), {"shard_id": shard_id, "active_rooms": Increment(-1),
                                                      "updated_at_ms": now_ms}, merge=True)
