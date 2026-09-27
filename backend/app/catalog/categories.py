"""Category/subcategory management (spec §8, §11 area 4).

Exactly nine global main categories are fixed in code; admins manage localised names and subcategories
through ``categories/{id}`` overrides, which clients read via the API (and Firestore rules allow reads).
"""

from __future__ import annotations

import time
from typing import Any

from app.common.errors import ApiError, ErrorCode
from app.questions.taxonomy import CATEGORIES


class CategoryService:
    def __init__(self, store, ttl_s: float = 30.0) -> None:
        self._store = store
        self._ttl = ttl_s
        self._cache: tuple[float, list[dict[str, Any]]] | None = None

    async def all(self) -> list[dict[str, Any]]:
        if self._cache and time.monotonic() - self._cache[0] < self._ttl:
            return self._cache[1]
        docs = await self._store.get_many([f"categories/{c.id}" for c in CATEGORIES])
        merged = []
        for category, doc in zip(CATEGORIES, docs, strict=True):
            doc = doc or {}
            subs = dict(category.subcategories)
            subs.update(doc.get("subcategories") or {})
            disabled = set(doc.get("disabled_subcategories") or [])
            merged.append({"id": category.id, "names": {**category.names, **(doc.get("names") or {})},
                           "icon": category.icon,
                           "subcategories": {sid: names for sid, names in subs.items() if sid not in disabled},
                           "disabled_subcategories": sorted(disabled)})
        self._cache = (time.monotonic(), merged)
        return merged

    def invalidate(self) -> None:
        self._cache = None

    async def update(self, category_id: str, *, names: dict[str, str] | None,
                     subcategories: dict[str, dict[str, str]] | None, disabled: list[str] | None,
                     now_ms: int) -> dict[str, Any]:
        if category_id not in {c.id for c in CATEGORIES}:
            raise ApiError(ErrorCode.NOT_FOUND, detail={"reason": "main_categories_are_fixed"})
        current = await self._store.get(f"categories/{category_id}") or {}
        doc = {**current, "schema_version": 1, "id": category_id, "updated_at_ms": now_ms}
        if names is not None:
            doc["names"] = names
        if subcategories is not None:
            doc["subcategories"] = subcategories
        if disabled is not None:
            doc["disabled_subcategories"] = sorted(set(disabled))
        await self._store.set(f"categories/{category_id}", doc)
        self.invalidate()
        return next(c for c in await self.all() if c["id"] == category_id)
