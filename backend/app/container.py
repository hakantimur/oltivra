"""Dependency container: adapters chosen by settings, services built lazily."""

from __future__ import annotations

from functools import cached_property
from typing import Any

import anyio

from app.auth.internal import InternalAuth, OidcInternalAuth, SharedSecretInternalAuth
from app.auth.verifiers import (
    AppCheckVerifier,
    DebugAppCheck,
    FakeTokenVerifier,
    FirebaseAppCheck,
    FirebaseTokenVerifier,
    NoAppCheck,
    TokenVerifier,
)
from app.common.clock import Clock, SystemClock
from app.common.idempotency import IdempotencyService
from app.common.keys import Keyring
from app.common.rate_limit import RateLimiter
from app.common.server_config import ServerConfigService
from app.common.settings import Settings
from app.common.store.docstore import DocStore
from app.common.store.livestore import LiveStore, MemoryLiveStore
from app.common.store.memory_docstore import MemoryDocStore
from app.common.tasks import CloudTasksScheduler, LocalTaskScheduler, RecordingScheduler, TaskScheduler


class Container:
    def __init__(
        self,
        settings: Settings,
        *,
        clock: Clock | None = None,
        store: DocStore | None = None,
        live: LiveStore | None = None,
        tasks: TaskScheduler | None = None,
        token_verifier: TokenVerifier | None = None,
        app_check: AppCheckVerifier | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> None:
        self.settings = settings
        self.clock: Clock = clock or SystemClock()
        self.keys = Keyring.from_settings(settings)
        self.io_limiter = anyio.CapacityLimiter(settings.blocking_io_threads)
        self.firebase_app = None
        if store is None or live is None:
            if settings.store_backend == "firebase":
                from app.common.firebase import build_firebase_stores

                self.firebase_app, fs_store, fs_live = build_firebase_stores(settings, self.io_limiter)
                store = store or fs_store
                live = live or fs_live
            else:
                store = store or MemoryDocStore()
                live = live or MemoryLiveStore(settings.shard_ids)
        self.store: DocStore = store
        self.live: LiveStore = live
        self.tasks: TaskScheduler = tasks or self._build_tasks()
        self.token_verifier: TokenVerifier = token_verifier or self._build_token_verifier()
        self.app_check: AppCheckVerifier = app_check or self._build_app_check()
        self.internal_auth: InternalAuth = self._build_internal_auth()
        for name, value in (overrides or {}).items():
            setattr(self, name, value)

    # ---- adapter builders ----
    def _build_tasks(self) -> TaskScheduler:
        mode = self.settings.tasks_mode
        if mode == "cloud":
            return CloudTasksScheduler(self.settings.cloud_tasks_project, self.settings.cloud_tasks_location,
                                       self.settings.task_target_base_url, self.settings.task_service_account,
                                       self.io_limiter)
        if mode == "recording":
            return RecordingScheduler()
        return LocalTaskScheduler(self.clock.now_ms)

    def _build_token_verifier(self) -> TokenVerifier:
        if self.settings.auth_mode == "fake":
            return FakeTokenVerifier()
        from app.common.firebase import default_app

        return FirebaseTokenVerifier(self.firebase_app or default_app(self.settings), self.io_limiter)

    def _build_app_check(self) -> AppCheckVerifier:
        mode = self.settings.app_check_mode
        if mode == "off":
            return NoAppCheck()
        from app.common.firebase import default_app

        inner = FirebaseAppCheck(self.firebase_app or default_app(self.settings), self.io_limiter)
        return DebugAppCheck(inner) if mode == "debug" else inner

    def _build_internal_auth(self) -> InternalAuth:
        if self.settings.internal_auth_mode == "oidc":
            return OidcInternalAuth(self.settings.task_target_base_url, {self.settings.task_service_account})
        return SharedSecretInternalAuth(self.settings.internal_shared_secret)

    # ---- shared services ----
    @cached_property
    def idempotency(self) -> IdempotencyService:
        return IdempotencyService(self.store, self.clock)

    @cached_property
    def rate_limiter(self) -> RateLimiter:
        return RateLimiter(self.store, self.clock)

    @cached_property
    def config(self) -> ServerConfigService:
        return ServerConfigService(self.store)

    # ---- question platform ----
    @cached_property
    def question_repo(self):
        from app.questions.repository import QuestionRepository

        return QuestionRepository(self.store, self.clock)

    @cached_property
    def manifest_cache(self):
        from app.manifests.manifest import ManifestCache

        return ManifestCache(self.store, check_interval_s=0 if self.settings.env == "test" else 5.0)

    @cached_property
    def manifest_builder(self):
        from app.manifests.manifest import ManifestBuilder

        return ManifestBuilder(self.store, self.clock)

    @cached_property
    def exposure(self):
        from app.questions.exposure import ExposureService

        return ExposureService(self.store, self.clock)

    @cached_property
    def question_plans(self):
        from app.questions.plan import QuestionPlanService

        return QuestionPlanService(self.manifest_cache, self.question_repo, self.exposure, self.clock)

    @cached_property
    def question_stats(self):
        from app.questions.stats import QuestionStatsService

        return QuestionStatsService(self.store)

    @cached_property
    def media_signer(self):
        from app.common.media import EmulatorMediaSigner, GcsMediaSigner

        if self.settings.env in ("stage", "prod"):
            return GcsMediaSigner(self.settings.storage_bucket, self.settings.task_service_account, self.io_limiter)
        return EmulatorMediaSigner("127.0.0.1:9199", self.settings.storage_bucket)

    # ---- lifecycle ----
    async def startup(self) -> None:
        from app.tasks.dispatch import dispatch_task

        async def dispatcher(body: dict[str, Any]) -> Any:
            return await dispatch_task(self, body)

        if hasattr(self.tasks, "dispatcher"):
            self.tasks.dispatcher = dispatcher

    async def shutdown(self) -> None:
        if isinstance(self.tasks, LocalTaskScheduler):
            await self.tasks.shutdown()
