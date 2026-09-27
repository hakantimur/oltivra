"""Transaction contention retry in the Firestore adapter (load test 2026-09-27)."""

from __future__ import annotations

import asyncio

import pytest
from google.api_core import exceptions as gexc

from app.common.store import firestore_docstore as fds


def _store(failures: int):
    store = fds.FirestoreDocStore.__new__(fds.FirestoreDocStore)
    calls = {"n": 0}

    async def run(fn):
        calls["n"] += 1
        if calls["n"] <= failures:
            raise gexc.Aborted("Aborted due to cross-transaction contention")
        return "ok"

    store._run = run
    return store, calls


def test_contention_is_retried_until_the_transaction_succeeds(monkeypatch):
    monkeypatch.setattr(fds, "TXN_CONTENTION_BASE_DELAY_S", 0)
    store, calls = _store(failures=3)
    assert asyncio.run(store.run_transaction(lambda txn: None)) == "ok"
    assert calls["n"] == 4


def test_contention_gives_up_after_the_attempt_budget(monkeypatch):
    monkeypatch.setattr(fds, "TXN_CONTENTION_BASE_DELAY_S", 0)
    store, calls = _store(failures=99)
    with pytest.raises(gexc.Aborted):
        asyncio.run(store.run_transaction(lambda txn: None))
    assert calls["n"] == fds.TXN_CONTENTION_ATTEMPTS
