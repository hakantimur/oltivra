"""Server-managed catalog lookups with a short cache. Avatar/reaction IDs are validated against the
*active* catalog (spec §2.3, §5)."""

from __future__ import annotations

import time
from typing import Any

from app.catalog.data import AVATARS, BADGES, FRAMES, REACTIONS
from app.common.store.docstore import DocStore, Query


class CatalogService:
    def __init__(self, store: DocStore, ttl_s: float = 30.0) -> None:
        self._store = store
        self._ttl = ttl_s
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    async def _load(self, collection: str, fallback: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
        cached = self._cache.get(collection)
        if cached and time.monotonic() - cached[0] < self._ttl:
            return cached[1]
        rows = [r.data for r in await self._store.query(Query(collection))]
        items = rows or [dict(item) for item in fallback]
        items.sort(key=lambda a: (a.get("sort", 0), a["id"]))
        self._cache[collection] = (time.monotonic(), items)
        return items

    async def avatars(self) -> list[dict[str, Any]]:
        return [a for a in await self._load("avatar_catalog", AVATARS) if a.get("active", True)]

    async def reactions(self) -> list[dict[str, Any]]:
        return [r for r in await self._load("reaction_catalog", REACTIONS) if r.get("active", True)]

    async def is_active_avatar(self, avatar_id: str) -> bool:
        return any(a["id"] == avatar_id for a in await self.avatars())

    async def is_active_reaction(self, reaction_id: str) -> bool:
        return any(r["id"] == reaction_id for r in await self.reactions())

    @staticmethod
    def frames() -> list[dict[str, Any]]:
        return [dict(f) for f in FRAMES]

    @staticmethod
    def badges() -> list[dict[str, Any]]:
        return [dict(b) for b in BADGES]

    def invalidate(self) -> None:
        self._cache.clear()
