"""Durable wake-up scheduling (spec §20). Tasks are at-least-once and never define fairness."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

import anyio

log = logging.getLogger("oltivra.tasks")


class TaskKind(StrEnum):
    ROUND_START = "ROUND_START"
    ROUND_RECOVERY = "ROUND_RECOVERY"
    ROUND_ADVANCE = "ROUND_ADVANCE"
    BOT_WINNER = "BOT_WINNER"
    SETTLEMENT = "SETTLEMENT"
    CLEANUP = "CLEANUP"
    PARTY_EXPIRY = "PARTY_EXPIRY"
    REMATCH_EXPIRY = "REMATCH_EXPIRY"
    QUESTION_BATCH = "QUESTION_BATCH"


QUEUE_FAMILY = {
    TaskKind.ROUND_START: "round-start",
    TaskKind.ROUND_RECOVERY: "round-recovery",
    TaskKind.ROUND_ADVANCE: "round-recovery",
    TaskKind.BOT_WINNER: "bot-winner",
    TaskKind.SETTLEMENT: "settlement",
    TaskKind.CLEANUP: "cleanup",
    TaskKind.PARTY_EXPIRY: "cleanup",
    TaskKind.REMATCH_EXPIRY: "cleanup",
    TaskKind.QUESTION_BATCH: "round-recovery",
}

ROUTE = {
    "round-start": "/internal/tasks/round-start",
    "round-recovery": "/internal/tasks/round-recovery",
    "bot-winner": "/internal/tasks/bot-winner",
    "settlement": "/internal/tasks/settlement",
    "cleanup": "/internal/tasks/cleanup",
}


@dataclass(frozen=True)
class TaskRequest:
    kind: TaskKind
    shard_id: str
    eta_ms: int
    payload: dict[str, Any] = field(default_factory=dict)
    dedupe_parts: tuple[str, ...] = ()

    @property
    def queue(self) -> str:
        return f"{QUEUE_FAMILY[self.kind]}-{self.shard_id.split('-')[-1]}"

    @property
    def route(self) -> str:
        return ROUTE[QUEUE_FAMILY[self.kind]]

    @property
    def name(self) -> str:
        """Unique, non-sequential name: hash prefix + identifying parts (spec §20.2)."""
        base = ":".join((self.kind.value, *self.dedupe_parts))
        prefix = hashlib.sha256(base.encode()).hexdigest()[:12]
        safe = "-".join(p.replace("_", "-") for p in self.dedupe_parts)[:300]
        return f"{prefix}-{self.kind.value.lower().replace('_', '-')}-{safe}"

    def body(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "task_kind": self.kind.value,
            "rtdb_shard_id": self.shard_id,
            "idempotency_key": self.name,
            **self.payload,
        }


class TaskScheduler(Protocol):
    async def schedule(self, task: TaskRequest) -> None: ...


Dispatcher = Callable[[dict[str, Any]], Awaitable[Any]]


class RecordingScheduler:
    """Collects tasks; tests dispatch them explicitly (optionally duplicated or delayed)."""

    def __init__(self) -> None:
        self.tasks: list[TaskRequest] = []
        self._names: set[str] = set()
        self.dispatcher: Dispatcher | None = None

    async def schedule(self, task: TaskRequest) -> None:
        if task.name in self._names:
            return
        self._names.add(task.name)
        self.tasks.append(task)

    def pending(self, kind: TaskKind | None = None) -> list[TaskRequest]:
        return [t for t in self.tasks if kind is None or t.kind == kind]

    async def run_due(self, now_ms: int) -> int:
        """Dispatch every task whose ETA has passed, in ETA order. Returns how many ran."""
        ran = 0
        while True:
            due = sorted((t for t in self.tasks if t.eta_ms <= now_ms), key=lambda t: t.eta_ms)
            if not due:
                return ran
            task = due[0]
            self.tasks.remove(task)
            assert self.dispatcher is not None
            await self.dispatcher(task.body())
            ran += 1


class LocalTaskScheduler:
    """In-process asyncio timers for local development (not durable; sync fallback covers loss)."""

    def __init__(self, now_ms: Callable[[], int], retries: int = 3) -> None:
        self._now_ms = now_ms
        self._names: set[str] = set()
        self._retries = retries
        self._tasks: set[asyncio.Task] = set()
        self.dispatcher: Dispatcher | None = None

    async def schedule(self, task: TaskRequest) -> None:
        if task.name in self._names:
            return
        self._names.add(task.name)
        handle = asyncio.get_running_loop().create_task(self._fire(task))
        self._tasks.add(handle)
        handle.add_done_callback(self._tasks.discard)

    async def _fire(self, task: TaskRequest) -> None:
        delay = max(0, task.eta_ms - self._now_ms()) / 1000
        await asyncio.sleep(delay)
        for attempt in range(self._retries + 1):
            try:
                assert self.dispatcher is not None
                await self.dispatcher(task.body())
                return
            except Exception:  # noqa: BLE001 - retried like Cloud Tasks, then logged
                log.exception("local task failed", extra={"task": task.name, "attempt": attempt})
                await asyncio.sleep(0.2 * (2**attempt))

    async def shutdown(self) -> None:
        for handle in list(self._tasks):
            handle.cancel()


class CloudTasksScheduler:
    def __init__(self, project: str, location: str, base_url: str, service_account: str,
                 limiter: anyio.CapacityLimiter) -> None:
        from google.cloud import tasks_v2

        self._tasks_v2 = tasks_v2
        self._client = tasks_v2.CloudTasksClient()
        self._project = project
        self._location = location
        self._base_url = base_url.rstrip("/")
        self._service_account = service_account
        self._limiter = limiter

    async def schedule(self, task: TaskRequest) -> None:
        from google.api_core import exceptions as gexc
        from google.protobuf import timestamp_pb2

        parent = self._client.queue_path(self._project, self._location, task.queue)
        eta = timestamp_pb2.Timestamp()
        eta.FromMilliseconds(task.eta_ms)
        request = {
            "name": f"{parent}/tasks/{task.name}",
            "schedule_time": eta,
            "http_request": {
                "http_method": self._tasks_v2.HttpMethod.POST,
                "url": f"{self._base_url}{task.route}",
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(task.body()).encode(),
                "oidc_token": {"service_account_email": self._service_account,
                               "audience": self._base_url},
            },
        }

        def create() -> None:
            try:
                self._client.create_task(parent=parent, task=request)
            except gexc.AlreadyExists:
                pass

        await anyio.to_thread.run_sync(create, limiter=self._limiter)
