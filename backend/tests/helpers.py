"""Shared test helpers: a seeded question platform snapshot reused across tests."""

from __future__ import annotations

import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from app.common.clock import FakeClock
from app.common.server_config import GameConfig, LeagueConfig, ServerConfigService
from app.common.store.memory_docstore import MemoryDocStore
from app.manifests.manifest import ManifestBuilder
from app.questions.models import QuestionStatus
from app.questions.repository import QuestionRepository
from app.questions.seed import SEED_LANGUAGES, import_seed


@lru_cache(maxsize=1)
def _seeded_snapshot() -> dict:
    async def build() -> dict:
        store, clock = MemoryDocStore(), FakeClock()
        repo = QuestionRepository(store, clock)
        await import_seed(repo, store, QuestionStatus.ACTIVE)
        await ManifestBuilder(store, clock).build_all(list(SEED_LANGUAGES))
        # Tests exercise the spec's ranked rule (bot matches are unranked) unless they opt into the league
        # bootstrap explicitly (tests/unit/test_leagues.py).
        config = GameConfig(leagues=LeagueConfig(bootstrap_active_humans=0))
        await store.set(f"server_config/v{config.config_version}", config.model_dump())
        await store.set(ServerConfigService.ACTIVE_PATH, {"config_version": config.config_version})
        return store.dump()

    # Run on a separate thread so this also works when called from inside a running event loop.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(build())).result()


def seeded_store() -> MemoryDocStore:
    """A fresh MemoryDocStore containing the imported seed content and built manifests."""
    store = MemoryDocStore()
    store._docs = copy.deepcopy(_seeded_snapshot())
    return store
