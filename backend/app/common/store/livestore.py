"""Live match store port with Firebase Realtime Database semantics over a shard ring (spec §14.1, §17).

RTDB drops ``None`` values and empty containers and turns dense integer-keyed maps into arrays.
``normalize_rtdb`` reproduces that so in-memory tests catch the same edge cases.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

R = TypeVar("R")


class _NoWrite:
    def __repr__(self) -> str:
        return "NO_WRITE"


NO_WRITE = _NoWrite()
"""Return as the new value from a transaction function to abort without writing."""


class LiveStore(Protocol):
    async def get(self, shard_id: str, path: str) -> Any: ...

    async def set(self, shard_id: str, path: str, value: Any) -> None: ...

    async def update(self, shard_id: str, path: str, values: dict[str, Any]) -> None: ...

    async def delete(self, shard_id: str, path: str) -> None: ...

    async def transaction(self, shard_id: str, path: str,
                          fn: Callable[[Any], tuple[Any, R]]) -> R: ...


_FORBIDDEN_KEY_CHARS = set(".$#[]/")


def normalize_rtdb(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key = str(key)
            if not key or _FORBIDDEN_KEY_CHARS & set(key):
                raise ValueError(f"invalid RTDB key: {key!r}")
            normalized = normalize_rtdb(item)
            if normalized is not None:
                out[key] = normalized
        if not out:
            return None
        if all(k.isdigit() for k in out):
            indices = [int(k) for k in out]
            if max(indices) < 2 * len(indices):
                arr: list[Any] = [None] * (max(indices) + 1)
                for k, item in out.items():
                    arr[int(k)] = item
                return arr
        return out
    if isinstance(value, list | tuple):
        return normalize_rtdb({str(i): v for i, v in enumerate(value)})
    if isinstance(value, bool | int | float | str) or value is None:
        return value
    raise TypeError(f"unsupported RTDB value type: {type(value).__name__}")


def _walk(root: dict[str, Any], path: str, create: bool) -> tuple[dict[str, Any] | None, str]:
    parts = [p for p in path.strip("/").split("/") if p]
    node: Any = root
    for part in parts[:-1]:
        if not isinstance(node, dict):
            return None, parts[-1]
        if part not in node or not isinstance(node[part], dict):
            if not create:
                return None, parts[-1]
            node[part] = {}
        node = node[part]
    return node, parts[-1]


class MemoryLiveStore:
    def __init__(self, shard_ids: list[str]) -> None:
        self._roots: dict[str, dict[str, Any]] = {sid: {} for sid in shard_ids}
        self._lock = threading.RLock()
        self.transaction_count = 0

    def _root(self, shard_id: str) -> dict[str, Any]:
        if shard_id not in self._roots:
            raise KeyError(f"unknown shard {shard_id}")
        return self._roots[shard_id]

    def _get(self, shard_id: str, path: str) -> Any:
        parent, leaf = _walk(self._root(shard_id), path, create=False)
        if parent is None:
            return None
        return copy.deepcopy(parent.get(leaf))

    def _set(self, shard_id: str, path: str, value: Any) -> None:
        normalized = normalize_rtdb(value)
        root = self._root(shard_id)
        parent, leaf = _walk(root, path, create=normalized is not None)
        if parent is None:
            return
        if normalized is None:
            parent.pop(leaf, None)
        else:
            parent[leaf] = normalized
        self._prune(root)

    def _prune(self, node: dict[str, Any]) -> None:
        for key in list(node):
            child = node[key]
            if isinstance(child, dict):
                self._prune(child)
                if not child:
                    node.pop(key)

    async def get(self, shard_id: str, path: str) -> Any:
        with self._lock:
            return self._get(shard_id, path)

    async def set(self, shard_id: str, path: str, value: Any) -> None:
        with self._lock:
            self._set(shard_id, path, value)

    async def update(self, shard_id: str, path: str, values: dict[str, Any]) -> None:
        with self._lock:
            base = path.strip("/")
            for rel, value in values.items():
                self._set(shard_id, f"{base}/{rel.strip('/')}" if base else rel, value)

    async def delete(self, shard_id: str, path: str) -> None:
        with self._lock:
            self._set(shard_id, path, None)

    async def transaction(self, shard_id: str, path: str, fn: Callable[[Any], tuple[Any, R]]) -> R:
        return self.transaction_sync(shard_id, path, fn)

    def transaction_sync(self, shard_id: str, path: str, fn: Callable[[Any], tuple[Any, R]]) -> R:
        with self._lock:
            self.transaction_count += 1
            current = self._get(shard_id, path)
            new_value, result = fn(current)
            if new_value is not NO_WRITE:
                self._set(shard_id, path, new_value)
            return result

    def dump(self, shard_id: str) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._root(shard_id))
