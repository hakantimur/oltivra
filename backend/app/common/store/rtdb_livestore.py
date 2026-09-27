"""Firebase RTDB shard-ring adapter: one firebase-admin app per shard database URL."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

import anyio
import firebase_admin
from anyio import CapacityLimiter
from firebase_admin import db

from app.common.store.livestore import NO_WRITE, normalize_rtdb

R = TypeVar("R")


class _Abort(Exception):
    pass


class RtdbLiveStore:
    def __init__(self, shard_urls: dict[str, str], project_id: str, limiter: CapacityLimiter,
                 credential=None) -> None:
        self._limiter = limiter
        self._apps: dict[str, firebase_admin.App] = {}
        for shard_id, url in shard_urls.items():
            name = f"rtdb-{shard_id}"
            try:
                app = firebase_admin.get_app(name)
            except ValueError:
                app = firebase_admin.initialize_app(credential, {"databaseURL": url, "projectId": project_id},
                                                    name=name)
            self._apps[shard_id] = app

    def _ref(self, shard_id: str, path: str) -> db.Reference:
        return db.reference("/" + path.strip("/"), app=self._apps[shard_id])

    async def _run(self, fn: Callable[[], R]) -> R:
        return await anyio.to_thread.run_sync(fn, limiter=self._limiter)

    async def get(self, shard_id: str, path: str) -> Any:
        return await self._run(lambda: self._ref(shard_id, path).get())

    async def set(self, shard_id: str, path: str, value: Any) -> None:
        normalized = normalize_rtdb(value)
        if normalized is None:
            await self.delete(shard_id, path)
            return
        await self._run(lambda: self._ref(shard_id, path).set(normalized))

    async def update(self, shard_id: str, path: str, values: dict[str, Any]) -> None:
        payload = {k.strip("/"): normalize_rtdb(v) for k, v in values.items()}
        await self._run(lambda: self._ref(shard_id, path).update(payload))

    async def delete(self, shard_id: str, path: str) -> None:
        await self._run(lambda: self._ref(shard_id, path).delete())

    async def transaction(self, shard_id: str, path: str, fn: Callable[[Any], tuple[Any, R]]) -> R:
        holder: dict[str, Any] = {}

        def update(current: Any) -> Any:
            new_value, result = fn(current)
            holder["result"] = result
            if new_value is NO_WRITE:
                raise _Abort()
            return normalize_rtdb(new_value)

        def run() -> R:
            try:
                self._ref(shard_id, path).transaction(update)
            except _Abort:
                pass
            return holder["result"]

        return await self._run(run)
