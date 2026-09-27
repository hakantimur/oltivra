"""In-memory DocStore with serialised transactions (tests and local memory mode)."""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable
from typing import Any, TypeVar

from app.common.store.docstore import (
    DELETE_FIELD,
    DocAlreadyExists,
    DocNotFound,
    DocSnapshot,
    Increment,
    Query,
    TxnReadAfterWrite,
    WriteOp,
    split_path,
)

T = TypeVar("T")
_MISSING = object()


def get_field(data: dict[str, Any], field_path: str) -> Any:
    current: Any = data
    for part in field_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _resolve_value(existing: Any, value: Any) -> Any:
    if isinstance(value, Increment):
        base = existing if isinstance(existing, int | float) and existing is not _MISSING else 0
        return base + value.amount
    return copy.deepcopy(value)


def _set_field(data: dict[str, Any], field_path: str, value: Any) -> None:
    parts = field_path.split(".")
    current = data
    for part in parts[:-1]:
        nxt = current.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            current[part] = nxt
        current = nxt
    leaf = parts[-1]
    if value is DELETE_FIELD:
        current.pop(leaf, None)
    else:
        current[leaf] = _resolve_value(current.get(leaf, _MISSING), value)


def _deep_merge(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if value is DELETE_FIELD:
            target.pop(key, None)
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = _resolve_value(target.get(key, _MISSING), value)


def _strip_sentinels(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in data.items():
        if value is DELETE_FIELD:
            continue
        if isinstance(value, Increment):
            out[key] = value.amount
        elif isinstance(value, dict):
            out[key] = _strip_sentinels(value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _matches(data: dict[str, Any], where: tuple) -> bool:
    for field_path, op, expected in where:
        actual = get_field(data, field_path)
        if op == "array_contains":
            if actual is _MISSING or not isinstance(actual, list) or expected not in actual:
                return False
            continue
        if actual is _MISSING:
            return False
        try:
            ok = {
                "==": lambda a, e: a == e,
                "!=": lambda a, e: a != e,
                "<": lambda a, e: a < e,
                "<=": lambda a, e: a <= e,
                ">": lambda a, e: a > e,
                ">=": lambda a, e: a >= e,
                "in": lambda a, e: a in e,
            }[op](actual, expected)
        except TypeError:
            return False
        if not ok:
            return False
    return True


class _SortKey:
    __slots__ = ("values", "directions")

    def __init__(self, values: list[Any], directions: list[str]) -> None:
        self.values = values
        self.directions = directions

    def __lt__(self, other: _SortKey) -> bool:
        for mine, theirs, direction in zip(self.values, other.values, self.directions, strict=True):
            if mine == theirs:
                continue
            less = mine < theirs
            return less if direction == "asc" else not less
        return False


class MemoryDocStore:
    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    # ---- raw helpers (lock held by caller) ----
    def _read(self, path: str) -> dict[str, Any] | None:
        doc = self._docs.get(path.strip("/"))
        return copy.deepcopy(doc) if doc is not None else None

    def _query(self, query: Query) -> list[DocSnapshot]:
        prefix = query.collection.strip("/")
        rows: list[DocSnapshot] = []
        for path, data in self._docs.items():
            coll, doc_id = split_path(path)
            if coll != prefix or not _matches(data, query.where):
                continue
            if any(get_field(data, f) is _MISSING for f, _ in query.order_by):
                continue
            rows.append(DocSnapshot(doc_id, path, copy.deepcopy(data)))
        if query.order_by:
            directions = [d for _, d in query.order_by] + ["asc"]
            rows.sort(key=lambda s: _SortKey([get_field(s.data, f) for f, _ in query.order_by] + [s.id],
                                             directions))
        else:
            rows.sort(key=lambda s: s.id)
        rows = rows[query.offset:]
        if query.limit is not None:
            rows = rows[: query.limit]
        return rows

    def _apply(self, op: WriteOp) -> None:
        path = op.path.strip("/")
        split_path(path)
        if op.kind == "delete":
            self._docs.pop(path, None)
        elif op.kind == "create":
            if path in self._docs:
                raise DocAlreadyExists(path)
            self._docs[path] = _strip_sentinels(op.data or {})
        elif op.kind == "set":
            self._docs[path] = _strip_sentinels(op.data or {})
        elif op.kind == "merge":
            doc = self._docs.setdefault(path, {})
            _deep_merge(doc, op.data or {})
        elif op.kind == "update":
            if path not in self._docs:
                raise DocNotFound(path)
            doc = self._docs[path]
            for field_path, value in (op.data or {}).items():
                _set_field(doc, field_path, value)
        else:
            raise ValueError(op.kind)

    def _validate(self, op: WriteOp) -> None:
        path = op.path.strip("/")
        if op.kind == "create" and path in self._docs:
            raise DocAlreadyExists(path)
        if op.kind == "update" and path not in self._docs:
            raise DocNotFound(path)

    # ---- DocStore API ----
    async def get(self, path: str) -> dict[str, Any] | None:
        with self._lock:
            return self._read(path)

    async def get_many(self, paths: list[str]) -> list[dict[str, Any] | None]:
        with self._lock:
            return [self._read(p) for p in paths]

    async def query(self, query: Query) -> list[DocSnapshot]:
        with self._lock:
            return self._query(query)

    async def set(self, path: str, data: dict[str, Any], merge: bool = False) -> None:
        with self._lock:
            self._apply(WriteOp("merge" if merge else "set", path, data))

    async def create(self, path: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._apply(WriteOp("create", path, data))

    async def update(self, path: str, fields: dict[str, Any]) -> None:
        with self._lock:
            self._apply(WriteOp("update", path, fields))

    async def delete(self, path: str) -> None:
        with self._lock:
            self._apply(WriteOp("delete", path))

    async def batch(self, ops: list[WriteOp]) -> None:
        with self._lock:
            for op in ops:
                self._validate(op)
            for op in ops:
                self._apply(op)

    async def run_transaction(self, fn: Callable[[Any], T]) -> T:
        return self.run_transaction_sync(fn)

    def run_transaction_sync(self, fn: Callable[[Any], T]) -> T:
        with self._lock:
            txn = _MemoryTxn(self)
            result = fn(txn)
            # Apply staged writes atomically; roll back on any failure.
            snapshot = copy.deepcopy(self._docs)
            try:
                for op in txn.ops:
                    self._apply(op)
            except Exception:
                self._docs = snapshot
                raise
            return result

    # ---- test helpers ----
    def dump(self, prefix: str = "") -> dict[str, dict[str, Any]]:
        with self._lock:
            return {p: copy.deepcopy(d) for p, d in self._docs.items() if p.startswith(prefix)}


class _MemoryTxn:
    def __init__(self, store: MemoryDocStore) -> None:
        self._store = store
        self.ops: list[WriteOp] = []

    def _check_read(self) -> None:
        if self.ops:
            raise TxnReadAfterWrite("transaction read after write")

    def get(self, path: str) -> dict[str, Any] | None:
        self._check_read()
        return self._store._read(path)

    def get_many(self, paths: list[str]) -> list[dict[str, Any] | None]:
        self._check_read()
        return [self._store._read(p) for p in paths]

    def query(self, query: Query) -> list[DocSnapshot]:
        self._check_read()
        return self._store._query(query)

    def set(self, path: str, data: dict[str, Any], merge: bool = False) -> None:
        self.ops.append(WriteOp("merge" if merge else "set", path, data))

    def create(self, path: str, data: dict[str, Any]) -> None:
        self.ops.append(WriteOp("create", path, data))

    def update(self, path: str, fields: dict[str, Any]) -> None:
        self.ops.append(WriteOp("update", path, fields))

    def delete(self, path: str) -> None:
        self.ops.append(WriteOp("delete", path))
