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


async def test_quick_match_root_round_trips_through_rtdb(stores):
    """The canonical root survives real RTDB normalisation and the engine keeps working on read-back."""
    from app.matches import engine
    from tests.engine_helpers import KEYS, T0, answer, new_match

    _, live = stores
    state, _ = new_match(humans=2, bots=2)
    match_id = state["match_id"] = f"it-{uuid.uuid4().hex[:8]}"
    path = f"matches/{match_id}"
    await live.transaction("live-02", path, lambda cur: (engine.project(state, KEYS), None))

    def step(cur):
        auth = cur["authoritative"]
        engine.resolve_due(auth, KEYS, auth["round"]["starts_at_ms"], "TEST")
        result = answer(auth, "u0", True, auth["round"]["starts_at_ms"] + 400)
        assert result.outcome.get("accepted"), result.outcome
        return engine.project(auth, KEYS), auth["state"]

    assert await live.transaction("live-02", path, step) == "ROUND_REVEAL"
    public = await live.get("live-02", f"{path}/public")
    assert public["correct_answer_reveal"]["points"] == 10
    assert "is_bot" not in str(public)
    assert T0 < public["reveal_ends_at_ms"]
    await live.delete("live-02", path)


async def test_survival_root_round_trips_through_rtdb(stores):
    from app.matches import engine
    from app.matches.model import Mode
    from tests.engine_helpers import KEYS, answer, new_match

    _, live = stores
    state, _ = new_match(Mode.SURVIVAL, humans=3, bots=1)
    match_id = state["match_id"] = f"it-{uuid.uuid4().hex[:8]}"
    path = f"matches/{match_id}"
    await live.transaction("live-03", path, lambda cur: (engine.project(state, KEYS), None))

    def play(cur):
        auth = cur["authoritative"]
        start = auth["round"]["starts_at_ms"]
        engine.resolve_due(auth, KEYS, start, "TEST")
        answer(auth, "u0", True, start + 400)
        answer(auth, "u1", False, start + 600)
        engine.resolve_due(auth, KEYS, auth["round"]["ends_at_ms"] + engine.GRACE_MS, "TEST")
        return engine.project(auth, KEYS), auth["state"]

    assert await live.transaction("live-03", path, play) == "ROUND_RESOLVE"

    def advance(cur):
        auth = cur["authoritative"]
        engine.resolve_due(auth, KEYS, auth["round"]["reveal_ends_at_ms"], "TEST")
        return engine.project(auth, KEYS), auth["state"]

    assert await live.transaction("live-03", path, advance) in ("ROUND_LOADING", "FINISHED_PENDING_SETTLEMENT")
    await live.delete("live-03", path)
