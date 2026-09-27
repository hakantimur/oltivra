"""Firestore DocStore adapter. Blocking SDK calls run on a bounded worker pool (spec §13.3)."""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any, TypeVar

import anyio
from anyio import CapacityLimiter
from google.api_core import exceptions as gexc
from google.cloud import firestore as gfs
from google.cloud.firestore_v1 import FieldFilter

from app.common.store.docstore import (
    DELETE_FIELD,
    DocAlreadyExists,
    DocNotFound,
    DocSnapshot,
    Increment,
    Query,
    WriteOp,
)

T = TypeVar("T")

_OPS = {"==": "==", "!=": "!=", "<": "<", "<=": "<=", ">": ">", ">=": ">=", "in": "in",
        "array_contains": "array_contains"}


TXN_CONTENTION_ATTEMPTS = 6
TXN_CONTENTION_BASE_DELAY_S = 0.025


def _encode(value: Any) -> Any:
    if value is DELETE_FIELD:
        return gfs.DELETE_FIELD
    if isinstance(value, Increment):
        return gfs.Increment(value.amount)
    if isinstance(value, dict):
        return {k: _encode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_encode(v) for v in value]
    return value


class FirestoreDocStore:
    def __init__(self, client: gfs.Client, limiter: CapacityLimiter) -> None:
        self._client = client
        self._limiter = limiter

    async def _run(self, fn: Callable[[], T]) -> T:
        return await anyio.to_thread.run_sync(fn, limiter=self._limiter)

    def _ref(self, path: str):
        return self._client.document(path.strip("/"))

    def _build_query(self, query: Query):
        q = self._client.collection(query.collection.strip("/"))
        for field_path, op, value in query.where:
            q = q.where(filter=FieldFilter(field_path, _OPS[op], value))
        for field_path, direction in query.order_by:
            q = q.order_by(field_path, direction=gfs.Query.DESCENDING if direction == "desc"
                           else gfs.Query.ASCENDING)
        if query.offset:
            q = q.offset(query.offset)
        if query.limit is not None:
            q = q.limit(query.limit)
        return q

    @staticmethod
    def _snap(doc) -> DocSnapshot:
        return DocSnapshot(doc.id, doc.reference.path, doc.to_dict() or {})

    async def get(self, path: str) -> dict[str, Any] | None:
        def _get():
            snap = self._ref(path).get()
            return snap.to_dict() if snap.exists else None
        return await self._run(_get)

    async def get_many(self, paths: list[str]) -> list[dict[str, Any] | None]:
        def _get_many():
            refs = [self._ref(p) for p in paths]
            by_path = {s.reference.path: (s.to_dict() if s.exists else None)
                       for s in self._client.get_all(refs)}
            return [by_path.get(r.path) for r in refs]
        return await self._run(_get_many)

    async def query(self, query: Query) -> list[DocSnapshot]:
        return await self._run(lambda: [self._snap(d) for d in self._build_query(query).stream()])

    async def set(self, path: str, data: dict[str, Any], merge: bool = False) -> None:
        await self._run(lambda: self._ref(path).set(_encode(data), merge=merge))

    async def create(self, path: str, data: dict[str, Any]) -> None:
        def _create():
            try:
                self._ref(path).create(_encode(data))
            except gexc.AlreadyExists as exc:
                raise DocAlreadyExists(path) from exc
        await self._run(_create)

    async def update(self, path: str, fields: dict[str, Any]) -> None:
        def _update():
            try:
                self._ref(path).update(_encode(fields))
            except gexc.NotFound as exc:
                raise DocNotFound(path) from exc
        await self._run(_update)

    async def delete(self, path: str) -> None:
        await self._run(lambda: self._ref(path).delete())

    async def batch(self, ops: list[WriteOp]) -> None:
        def _batch():
            batch = self._client.batch()
            for op in ops:
                _apply_write(batch, self._ref(op.path), op)
            try:
                batch.commit()
            except gexc.AlreadyExists as exc:
                raise DocAlreadyExists(str(exc)) from exc
            except gexc.NotFound as exc:
                raise DocNotFound(str(exc)) from exc
        await self._run(_batch)

    async def run_transaction(self, fn: Callable[[Any], T]) -> T:
        def _txn():
            transaction = self._client.transaction(max_attempts=10)

            @gfs.transactional
            def body(txn):
                return fn(_FirestoreTxn(self, txn))

            try:
                return body(transaction)
            except gexc.AlreadyExists as exc:
                raise DocAlreadyExists(str(exc)) from exc
            except gexc.NotFound as exc:
                raise DocNotFound(str(exc)) from exc

        # ``transactional`` only retries commit conflicts; contention reported while reading inside the transaction
        # (409 Aborted) surfaces here. Transaction bodies are retry-safe, so retry with jittered backoff (load test
        # 2026-09-27: hot matchmaking and settlement documents under 300 concurrent players).
        for attempt in range(1, TXN_CONTENTION_ATTEMPTS + 1):
            try:
                return await self._run(_txn)
            except gexc.Aborted:
                if attempt == TXN_CONTENTION_ATTEMPTS:
                    raise
                await anyio.sleep(random.uniform(0, TXN_CONTENTION_BASE_DELAY_S * 2 ** attempt))
        raise AssertionError("unreachable")


def _apply_write(writer, ref, op: WriteOp) -> None:
    if op.kind == "delete":
        writer.delete(ref)
    elif op.kind == "create":
        writer.create(ref, _encode(op.data or {}))
    elif op.kind == "set":
        writer.set(ref, _encode(op.data or {}))
    elif op.kind == "merge":
        writer.set(ref, _encode(op.data or {}), merge=True)
    elif op.kind == "update":
        writer.update(ref, _encode(op.data or {}))
    else:
        raise ValueError(op.kind)


class _FirestoreTxn:
    def __init__(self, store: FirestoreDocStore, txn) -> None:
        self._store = store
        self._txn = txn

    def get(self, path: str) -> dict[str, Any] | None:
        snap = self._store._ref(path).get(transaction=self._txn)
        return snap.to_dict() if snap.exists else None

    def get_many(self, paths: list[str]) -> list[dict[str, Any] | None]:
        refs = [self._store._ref(p) for p in paths]
        by_path = {s.reference.path: (s.to_dict() if s.exists else None)
                   for s in self._txn.get_all(refs)}
        return [by_path.get(r.path) for r in refs]

    def query(self, query: Query) -> list[DocSnapshot]:
        return [FirestoreDocStore._snap(d) for d in self._txn.get(self._store._build_query(query))]

    def set(self, path: str, data: dict[str, Any], merge: bool = False) -> None:
        _apply_write(self._txn, self._store._ref(path), WriteOp("merge" if merge else "set", path, data))

    def create(self, path: str, data: dict[str, Any]) -> None:
        _apply_write(self._txn, self._store._ref(path), WriteOp("create", path, data))

    def update(self, path: str, fields: dict[str, Any]) -> None:
        _apply_write(self._txn, self._store._ref(path), WriteOp("update", path, fields))

    def delete(self, path: str) -> None:
        self._txn.delete(self._store._ref(path))
