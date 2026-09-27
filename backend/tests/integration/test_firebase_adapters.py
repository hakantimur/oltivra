"""Firestore / RTDB adapters against the emulator suite: ``docker compose up -d emulators``."""

from __future__ import annotations

import os
import uuid

import anyio
import pytest

pytestmark = pytest.mark.integration

os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
os.environ.setdefault("FIREBASE_DATABASE_EMULATOR_HOST", "127.0.0.1:9000")
os.environ.setdefault("FIREBASE_AUTH_EMULATOR_HOST", "127.0.0.1:9099")

from app.common.settings import Settings  # noqa: E402
from app.common.store.docstore import DocAlreadyExists, Increment, Query  # noqa: E402
from app.common.store.livestore import NO_WRITE  # noqa: E402


@pytest.fixture(scope="module")
def stores():
    from app.common.firebase import build_firebase_stores

    settings = Settings(env="test", store_backend="firebase", shard_count=4)
    _, doc_store, live_store = build_firebase_stores(settings, anyio.CapacityLimiter(8))
    return doc_store, live_store


async def test_firestore_crud_query_transaction(stores):
    store, _ = stores
    coll = f"it_{uuid.uuid4().hex[:8]}"
    await store.create(f"{coll}/a", {"n": 1, "state": "QUEUED", "tags": ["x"]})
    with pytest.raises(DocAlreadyExists):
        await store.create(f"{coll}/a", {"n": 2})
    await store.set(f"{coll}/b", {"n": 5, "state": "QUEUED", "tags": ["y"]})
    await store.update(f"{coll}/a", {"n": Increment(2)})
    assert (await store.get(f"{coll}/a"))["n"] == 3
    rows = await store.query(Query(coll).filter("state", "==", "QUEUED").order("n", "desc"))
    assert [r.id for r in rows] == ["b", "a"]

    def move(txn):
        a, b = txn.get_many([f"{coll}/a", f"{coll}/b"])
        txn.update(f"{coll}/a", {"n": a["n"] + b["n"]})
        return a["n"] + b["n"]

    assert await store.run_transaction(move) == 8
    assert (await store.get(f"{coll}/a"))["n"] == 8


async def test_rtdb_shard_transaction(stores):
    _, live = stores
    match = f"m_{uuid.uuid4().hex[:8]}"
    path = f"matches/{match}"
    assert await live.transaction("live-01", path, lambda cur: ({"v": 1, "empty": {}}, cur)) is None
    assert await live.get("live-01", path) == {"v": 1}
    assert await live.transaction("live-01", path, lambda cur: (NO_WRITE, cur["v"])) == 1
    assert await live.get("live-00", path) is None  # shards are isolated
    await live.delete("live-01", path)
    assert await live.get("live-01", path) is None
