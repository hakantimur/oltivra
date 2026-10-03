from __future__ import annotations

import threading
import uuid

import pytest
from pydantic import ValidationError

from app.common.clock import FakeClock, iso_week_id, utc_date_id
from app.common.errors import ApiError, ErrorCode
from app.common.idempotency import IdempotencyService, resolve_key
from app.common.keys import HmacKey
from app.common.rate_limit import Limit, RateLimiter
from app.common.server_config import GameConfig, RankedConfig
from app.common.settings import Settings
from app.common.store.docstore import DELETE_FIELD, DocAlreadyExists, Increment, Query, TxnReadAfterWrite
from app.common.store.livestore import NO_WRITE, MemoryLiveStore, normalize_rtdb
from app.common.store.memory_docstore import MemoryDocStore
from app.common.tasks import TaskKind, TaskRequest


def test_health_and_ping(api, client):
    assert client.get("/healthz").json() == {"status": "ok"}
    res = api.get("/v1/ping", "u1")
    assert res.status_code == 200
    assert res.json()["server_received_at_ms"] <= res.json()["server_responded_at_ms"]


def test_error_envelope_for_missing_auth(client):
    res = client.get("/v1/ping")
    assert res.status_code == 401
    body = res.json()["error"]
    assert body["code"] == "UNAUTHENTICATED"
    assert body["message_key"] == "error.unauthenticated"
    assert body["retryable"] is False
    assert body["request_id"] == res.headers["x-request-id"]


def test_unknown_route_uses_envelope(client):
    res = client.get("/v1/nope")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"


def test_internal_routes_reject_user_tokens(client):
    res = client.post("/internal/tasks/round-recovery", json={"task_kind": "ROUND_RECOVERY"},
                      headers={"authorization": "Bearer test:u1"})
    assert res.status_code == 403


def test_internal_task_must_match_its_queue_family(client):
    headers = {"x-internal-auth": "dev-internal-secret"}
    res = client.post("/internal/tasks/cleanup", json={"task_kind": "SETTLEMENT", "match_id": "m", "rtdb_shard_id":
                                                       "live-00"}, headers=headers)
    assert res.status_code == 400 and res.json()["error"]["detail"]["reason"] == "task_family_mismatch"
    res = client.post("/internal/tasks/cleanup", json={"task_kind": "NOPE"}, headers=headers)
    assert res.json()["error"]["detail"]["reason"] == "unknown_task_kind"


@pytest.mark.parametrize("overrides", [
    {"env": "prod", "auth_mode": "fake"},
    {"env": "stage", "store_backend": "memory", "auth_mode": "firebase"},
    {"env": "prod", "auth_mode": "firebase", "store_backend": "firebase", "app_check_mode": "debug",
     "admob_ssv_mode": "google", "purchase_verify_mode": "store"},
])
def test_production_guards(overrides):
    with pytest.raises(ValidationError):
        Settings(**overrides)


def test_hmac_key_rotation_and_verify():
    key = HmacKey("k2:new,k1:old")
    sig = key.hexdigest("m")
    assert key.verify("m", sig, "k2")
    assert key.verify("m", key.hexdigest("m", "k1"), "k1")
    assert not key.verify("m", sig, "k1")
    assert not key.verify("m", sig, "missing")
    assert 0 <= key.first_uint32("m") < 2**32


def test_week_and_day_ids():
    ms = 1_790_000_000_000  # 2026-09-21
    assert utc_date_id(ms) == "2026-09-21"
    assert iso_week_id(ms) == "2026-W39"


async def test_memory_store_query_order_and_filters():
    store = MemoryDocStore()
    rows_in = [("QUEUED", 1000), ("QUEUED", 900), ("CANCELLED", 950), ("QUEUED", 1100)]
    for i, (state, mmr) in enumerate(rows_in):
        await store.set(f"tickets/t{i}", {"state": state, "mmr": mmr, "created_at": i, "tags": ["a"]})
    rows = await store.query(Query("tickets").filter("state", "==", "QUEUED").order("mmr", "desc").take(2))
    assert [r.id for r in rows] == ["t3", "t0"]
    rows = await store.query(Query("tickets").filter("mmr", ">=", 950).filter("tags", "array_contains", "a"))
    assert {r.id for r in rows} == {"t0", "t2", "t3"}


async def test_memory_store_update_sentinels_and_create():
    store = MemoryDocStore()
    await store.create("c/d", {"n": 1, "nested": {"x": 1, "y": 2}})
    with pytest.raises(DocAlreadyExists):
        await store.create("c/d", {})
    await store.update("c/d", {"n": Increment(4), "nested.y": DELETE_FIELD, "nested.z": 3})
    assert await store.get("c/d") == {"n": 5, "nested": {"x": 1, "z": 3}}


async def test_memory_transaction_rejects_read_after_write():
    store = MemoryDocStore()

    def bad(txn):
        txn.set("a/b", {"x": 1})
        txn.get("a/c")

    with pytest.raises(TxnReadAfterWrite):
        await store.run_transaction(bad)
    assert await store.get("a/b") is None


def test_memory_transactions_serialise_under_threads():
    store = MemoryDocStore()
    store.run_transaction_sync(lambda t: t.set("ctr/x", {"n": 0}))

    def incr(txn):
        doc = txn.get("ctr/x")
        txn.set("ctr/x", {"n": doc["n"] + 1})

    def worker():
        for _ in range(50):
            store.run_transaction_sync(incr)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert store.dump("ctr")["ctr/x"]["n"] == 400


def test_rtdb_normalisation_mirrors_firebase():
    assert normalize_rtdb({"a": None, "b": {}, "c": [], "d": 1}) == {"d": 1}
    assert normalize_rtdb({"0": "x", "1": "y"}) == ["x", "y"]
    assert normalize_rtdb({"A": "x", "B": "y"}) == {"A": "x", "B": "y"}
    with pytest.raises(ValueError):
        normalize_rtdb({"a.b": 1})


async def test_live_store_transaction_and_abort():
    live = MemoryLiveStore(["live-00"])
    result = await live.transaction("live-00", "matches/m1", lambda cur: ({"v": 1}, "created"))
    assert result == "created"
    result = await live.transaction("live-00", "matches/m1", lambda cur: (NO_WRITE, cur["v"]))
    assert result == 1
    assert await live.get("live-00", "matches/m1/v") == 1
    await live.delete("live-00", "matches/m1")
    assert await live.get("live-00", "matches") is None


async def test_idempotency_replay_and_reuse():
    store, clock = MemoryDocStore(), FakeClock()
    svc = IdempotencyService(store, clock)
    calls = []

    async def handler():
        calls.append(1)
        return {"n": len(calls)}

    key = str(uuid.uuid4())
    first = await svc.execute("u", "ep", key, {"a": 1, "request_id": key}, handler)
    again = await svc.execute("u", "ep", key, {"a": 1, "request_id": key}, handler)
    assert first == again == {"n": 1}
    with pytest.raises(ApiError) as err:
        await svc.execute("u", "ep", key, {"a": 2}, handler)
    assert err.value.code == ErrorCode.IDEMPOTENCY_KEY_REUSED
    assert await svc.execute("v", "ep", key, {"a": 2}, handler) == {"n": 2}


async def test_idempotency_replays_deterministic_errors_but_not_retryable():
    store, clock = MemoryDocStore(), FakeClock()
    svc = IdempotencyService(store, clock)
    attempts = []

    async def failing():
        attempts.append(1)
        raise ApiError(ErrorCode.INVALID_OPTION)

    key = str(uuid.uuid4())
    for _ in range(2):
        with pytest.raises(ApiError) as err:
            await svc.execute("u", "ep", key, {}, failing)
        assert err.value.code == ErrorCode.INVALID_OPTION
    assert len(attempts) == 1

    async def flaky():
        attempts.append(1)
        raise ApiError(ErrorCode.RATE_LIMITED)

    key2 = str(uuid.uuid4())
    for _ in range(2):
        with pytest.raises(ApiError):
            await svc.execute("u", "ep", key2, {}, flaky)
    assert len(attempts) == 3


def test_resolve_key_rules():
    key = str(uuid.uuid4())
    assert resolve_key(key, key) == key
    assert resolve_key(None, key) == key
    with pytest.raises(ApiError):
        resolve_key(key, str(uuid.uuid4()))
    with pytest.raises(ApiError):
        resolve_key(None, "not-a-uuid")


async def test_rate_limiter_window():
    store, clock = MemoryDocStore(), FakeClock(start_ms=1_000_000_000_000)
    limiter = RateLimiter(store, clock)
    limit = Limit("t", 2, 10)
    await limiter.hit(limit, "u")
    await limiter.hit(limit, "u")
    with pytest.raises(ApiError) as err:
        await limiter.hit(limit, "u")
    assert err.value.code == ErrorCode.RATE_LIMITED and err.value.retry_after_s >= 1
    clock.advance(10_000)
    await limiter.hit(limit, "u")


def test_ranked_config_cannot_be_weakened():
    with pytest.raises(ValidationError):
        RankedConfig(quick_min_total_humans=2)
    assert GameConfig().quick.wrong_penalty == -6


def test_task_names_are_unique_and_queue_by_shard():
    a = TaskRequest(TaskKind.ROUND_RECOVERY, "live-07", 0, {}, ("m1", "r1"))
    b = TaskRequest(TaskKind.ROUND_RECOVERY, "live-07", 0, {}, ("m1", "r2"))
    assert a.name != b.name and a.queue == "round-recovery-07"
    assert TaskRequest(TaskKind.ROUND_ADVANCE, "live-03", 0).queue == "round-recovery-03"


def test_app_check_monitor_mode_logs_but_never_rejects():
    import asyncio

    from app.auth.verifiers import MonitorAppCheck, StaticAppCheck

    monitor = MonitorAppCheck(StaticAppCheck())
    asyncio.run(monitor.verify(None))
    asyncio.run(monitor.verify("bad"))
    asyncio.run(monitor.verify("valid-app-check"))


def test_app_check_monitor_logs_reason_and_client(caplog):
    import asyncio
    import json
    import logging

    from app.auth.verifiers import MonitorAppCheck, StaticAppCheck
    from app.common.logging import JsonFormatter, client_var

    monitor = MonitorAppCheck(StaticAppCheck())
    token = client_var.set("android/9")
    try:
        with caplog.at_level(logging.WARNING):
            asyncio.run(monitor.verify(None))
            asyncio.run(monitor.verify("not-a-jwt"))
        lines = [json.loads(JsonFormatter().format(r)) for r in caplog.records]
    finally:
        client_var.reset(token)
    assert [line["has_token"] for line in lines] == [False, True]
    assert lines[0]["reason"] == "missing_token" and lines[0]["token_app"] == "-"
    assert lines[1]["token_app"] == "malformed"
    assert all(line["client"] == "android/9" for line in lines)
    assert all("not-a-jwt" not in json.dumps(line) for line in lines)


def test_request_logs_carry_client_headers():
    from app.main import _client

    class _Req:
        def __init__(self, headers):
            self.headers = headers

    assert _client(_Req({"x-client-platform": "ios", "x-client-build": "12"})) == "ios/12"
    assert _client(_Req({})) == "-"
    assert _client(_Req({"x-client-platform": "a" * 100})) == "a" * 16 + "/?"
