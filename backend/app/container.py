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

    @cached_property
    def media_uploader(self):
        from app.common.media import EmulatorMediaUploader, GcsMediaUploader, MemoryMediaUploader

        if self.settings.env in ("stage", "prod"):
            return GcsMediaUploader(self.settings.storage_bucket, self.io_limiter)
        if self.settings.store_backend == "firebase":
            return EmulatorMediaUploader("127.0.0.1:9199", self.settings.storage_bucket)
        return MemoryMediaUploader()

    # ---- accounts & safety ----
    @cached_property
    def auth_admin(self):
        from app.auth.admin import FakeAuthAdmin, FirebaseAuthAdmin

        if self.settings.auth_mode == "fake":
            return FakeAuthAdmin()
        from app.common.firebase import default_app

        return FirebaseAuthAdmin(self.firebase_app or default_app(self.settings), self.io_limiter)

    @cached_property
    def catalog(self):
        from app.catalog.service import CatalogService

        return CatalogService(self.store, ttl_s=0 if self.settings.env == "test" else 30.0)

    @cached_property
    def categories(self):
        from app.catalog.categories import CategoryService

        return CategoryService(self.store, ttl_s=0 if self.settings.env == "test" else 30.0)

    @cached_property
    def duplicates(self):
        from app.admin.duplicates import DuplicateService

        return DuplicateService(self)

    @cached_property
    def pool_health(self):
        from app.admin.pool_health import PoolHealthService

        return PoolHealthService(self)

    @cached_property
    def audit(self):
        from app.admin.audit import AuditLog

        return AuditLog(self.store, self.clock)

    @cached_property
    def profiles(self):
        from app.profiles.service import ProfileService

        return ProfileService(self.store, self.clock, self.keys, self.catalog)

    @cached_property
    def safety(self):
        from app.moderation.safety import SafetyService

        return SafetyService(self.store, self.clock)

    @cached_property
    def maintenance(self):
        from app.maintenance.service import MaintenanceService

        return MaintenanceService(self)

    @cached_property
    def ai_generation(self):
        from app.admin.ai_generation import AnthropicQuestionGenerator, FakeQuestionGenerator, GenerationService

        if self.settings.ai_provider == "anthropic":
            generator = AnthropicQuestionGenerator(self.settings.anthropic_api_key, self.settings.ai_model)
        else:
            generator = FakeQuestionGenerator()
        return GenerationService(self, generator)

    @cached_property
    def sanctions(self):
        from app.moderation.sanctions import SanctionService

        return SanctionService(self)

    @cached_property
    def risk(self):
        from app.moderation.risk import RiskService

        return RiskService(self)

    @cached_property
    def deletion(self):
        from app.accounts.deletion import DeletionService

        return DeletionService(self.store, self.clock, self.keys, self.auth_admin)

    # ---- live matches ----
    @cached_property
    def bots(self):
        from app.bots.catalog import BotPool

        return BotPool(self.store, self.keys)

    @cached_property
    def shard_admission(self):
        from app.matches.shards import ShardAdmission

        return ShardAdmission(self.store)

    @cached_property
    def matches(self):
        from app.matches.service import MatchService

        return MatchService(self)

    @cached_property
    def match_factory(self):
        from app.matches.factory import MatchFactory

        return MatchFactory(self)

    @cached_property
    def matchmaking(self):
        from app.matchmaking.service import MatchmakingService

        return MatchmakingService(self)

    @cached_property
    def survival_refill(self):
        from app.survival.refill import SurvivalRefill

        return SurvivalRefill(self)

    @cached_property
    def progression(self):
        from app.progression.service import ProgressionHooks

        return ProgressionHooks(self)

    @cached_property
    def missions(self):
        from app.missions.service import MissionService

        return MissionService(self)

    @cached_property
    def question_reports(self):
        from app.moderation.question_reports import QuestionReportService

        return QuestionReportService(self)

    @cached_property
    def leaderboard(self):
        from app.progression.leaderboard import LeaderboardService

        return LeaderboardService(self)

    @cached_property
    def notifications(self):
        from app.notifications.service import FcmPushSender, NotificationService, RecordingPushSender

        if self.settings.auth_mode == "fake":
            sender = RecordingPushSender()
        else:
            from app.common.firebase import default_app

            sender = FcmPushSender(self.firebase_app or default_app(self.settings), self.io_limiter)
        return NotificationService(self.store, self.clock, sender)

    @cached_property
    def friends(self):
        from app.friends.service import FriendService

        return FriendService(self)

    @cached_property
    def parties(self):
        from app.parties.service import PartyService

        return PartyService(self)

    @cached_property
    def rewards(self):
        from app.ads.rewards import AdMobSsvVerifier, DevSsvVerifier, RewardService

        if self.settings.admob_ssv_mode == "google":
            verifier = AdMobSsvVerifier()
        else:
            verifier = DevSsvVerifier(self.settings.internal_shared_secret)
        return RewardService(self, verifier)

    @cached_property
    def purchases(self):
        from app.purchases.service import PurchaseService
        from app.purchases.verifiers import AppleJwsVerifier, FakeAppleVerifier, FakeGooglePlay, GooglePlayApiClient

        if self.settings.purchase_verify_mode == "store":
            paths = [p.strip() for p in self.settings.apple_root_cert_paths.split(",") if p.strip()]
            return PurchaseService(self, GooglePlayApiClient(self.settings.google_play_package, self.io_limiter),
                                   AppleJwsVerifier.from_paths(paths))
        return PurchaseService(self, FakeGooglePlay(), FakeAppleVerifier(self.settings.internal_shared_secret))

    @cached_property
    def settlement(self):
        from app.settlement.service import SettlementService

        return SettlementService(self)

    # ---- lifecycle ----
    async def startup(self) -> None:
        from app.tasks.dispatch import dispatch_task

        async def dispatcher(body: dict[str, Any]) -> Any:
            return await dispatch_task(self, body)

        if hasattr(self.tasks, "dispatcher"):
            self.tasks.dispatcher = dispatcher
        if self.settings.store_backend == "memory":
            from app.catalog.data import seed_catalogs

            await seed_catalogs(self.store)
            from app.bots.catalog import seed_bots

            await seed_bots(self.store, self.keys, self.clock.now_ms())
            if self.settings.env == "dev":
                await self._seed_dev_questions()

    async def _seed_dev_questions(self) -> None:
        """An in-memory dev server starts with the seed pool ACTIVE so matches can form without the emulator."""
        from app.common.store.docstore import Query
        from app.questions.models import QuestionStatus
        from app.questions.seed import SEED_LANGUAGES, import_seed

        if await self.store.query(Query("question_groups").take(1)):
            return
        await import_seed(self.question_repo, self.store, QuestionStatus.ACTIVE)
        await self.manifest_builder.build_all(list(SEED_LANGUAGES))

    async def shutdown(self) -> None:
        if isinstance(self.tasks, LocalTaskScheduler):
            await self.tasks.shutdown()
