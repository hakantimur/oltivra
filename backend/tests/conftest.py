from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.common.clock import FakeClock
from app.common.settings import Settings
from app.common.store.livestore import MemoryLiveStore
from app.common.tasks import RecordingScheduler
from app.container import Container
from app.main import create_app
from tests.helpers import seeded_store


def make_settings(**overrides: Any) -> Settings:
    base = dict(env="test", store_backend="memory", auth_mode="fake", app_check_mode="off",
                tasks_mode="recording", shard_count=4)
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def container(clock: FakeClock) -> Container:
    settings = make_settings()
    return Container(settings, clock=clock, store=seeded_store(), live=MemoryLiveStore(settings.shard_ids),
                     tasks=RecordingScheduler())


@pytest.fixture
def client(container: Container):
    with TestClient(create_app(container)) as test_client:
        yield test_client


class Api:
    """Sends authenticated, idempotent requests like the mobile client."""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def headers(self, uid: str | None, key: str | None = None, extra: str = "") -> dict[str, str]:
        headers: dict[str, str] = {}
        if uid:
            headers["authorization"] = f"Bearer test:{uid}{extra}"
        if key:
            headers["x-idempotency-key"] = key
        return headers

    def get(self, path: str, uid: str | None, extra: str = "", **params: Any):
        return self.client.get(path, headers=self.headers(uid, extra=extra), params=params or None)

    def _send(self, method: str, path: str, uid: str | None, body: dict[str, Any] | None, key: str | None,
              extra: str):
        body = dict(body or {})
        key = key or body.get("request_id") or str(uuid.uuid4())
        body.setdefault("request_id", key)
        return self.client.request(method, path, json=body, headers=self.headers(uid, key, extra))

    def post(self, path: str, uid: str | None, body: dict[str, Any] | None = None, key: str | None = None,
             extra: str = ""):
        return self._send("POST", path, uid, body, key, extra)

    def patch(self, path: str, uid: str | None, body: dict[str, Any] | None = None, key: str | None = None,
              extra: str = ""):
        return self._send("PATCH", path, uid, body, key, extra)

    def put(self, path: str, uid: str | None, body: dict[str, Any] | None = None, key: str | None = None,
            extra: str = ""):
        return self._send("PUT", path, uid, body, key, extra)

    def delete(self, path: str, uid: str | None, body: dict[str, Any] | None = None, key: str | None = None,
               extra: str = ""):
        return self._send("DELETE", path, uid, body, key, extra)


@pytest.fixture
def api(client: TestClient) -> Api:
    return Api(client)
