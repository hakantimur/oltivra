"""Persistent document store port with Firestore semantics.

Paths are slash-separated document paths (``users/uid_1``). Transactions take a *synchronous*
function that may be re-run on contention; it must perform all reads before its first write.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

T = TypeVar("T")


class DocAlreadyExists(Exception):
    pass


class DocNotFound(Exception):
    pass


class TxnReadAfterWrite(Exception):
    """Firestore transactions require every read before the first write."""


@dataclass(frozen=True)
class Increment:
    amount: int | float


class _DeleteField:
    _instance: _DeleteField | None = None

    def __new__(cls) -> _DeleteField:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "DELETE_FIELD"


DELETE_FIELD = _DeleteField()

FilterOp = str  # "==", "!=", "<", "<=", ">", ">=", "in", "array_contains"


@dataclass(frozen=True)
class Query:
    collection: str
    where: tuple[tuple[str, FilterOp, Any], ...] = ()
    order_by: tuple[tuple[str, str], ...] = ()
    limit: int | None = None
    offset: int = 0

    def filter(self, field_path: str, op: FilterOp, value: Any) -> Query:
        return Query(self.collection, (*self.where, (field_path, op, value)), self.order_by, self.limit,
                     self.offset)

    def order(self, field_path: str, direction: str = "asc") -> Query:
        if direction not in ("asc", "desc"):
            raise ValueError(direction)
        return Query(self.collection, self.where, (*self.order_by, (field_path, direction)), self.limit,
                     self.offset)

    def take(self, limit: int, offset: int = 0) -> Query:
        return Query(self.collection, self.where, self.order_by, limit, offset)


@dataclass
class DocSnapshot:
    id: str
    path: str
    data: dict[str, Any] = field(default_factory=dict)


class Txn(Protocol):
    def get(self, path: str) -> dict[str, Any] | None: ...

    def get_many(self, paths: list[str]) -> list[dict[str, Any] | None]: ...

    def query(self, query: Query) -> list[DocSnapshot]: ...

    def set(self, path: str, data: dict[str, Any], merge: bool = False) -> None: ...

    def create(self, path: str, data: dict[str, Any]) -> None: ...

    def update(self, path: str, fields: dict[str, Any]) -> None: ...

    def delete(self, path: str) -> None: ...


@dataclass(frozen=True)
class WriteOp:
    kind: str  # set | merge | update | create | delete
    path: str
    data: dict[str, Any] | None = None


class DocStore(Protocol):
    async def get(self, path: str) -> dict[str, Any] | None: ...

    async def get_many(self, paths: list[str]) -> list[dict[str, Any] | None]: ...

    async def query(self, query: Query) -> list[DocSnapshot]: ...

    async def set(self, path: str, data: dict[str, Any], merge: bool = False) -> None: ...

    async def create(self, path: str, data: dict[str, Any]) -> None: ...

    async def update(self, path: str, fields: dict[str, Any]) -> None: ...

    async def delete(self, path: str) -> None: ...

    async def batch(self, ops: list[WriteOp]) -> None: ...

    async def run_transaction(self, fn: Callable[[Txn], T]) -> T: ...


def split_path(path: str) -> tuple[str, str]:
    """Return (collection_path, doc_id)."""
    parts = path.strip("/").split("/")
    if len(parts) % 2 != 0:
        raise ValueError(f"not a document path: {path}")
    return "/".join(parts[:-1]), parts[-1]
