"""Session bootstrap and client presentation config (spec §15.1, §27.1–27.2, §32.1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.accounts.runtime import current, pointer, runtime_path
from app.catalog.data import CATALOG_VERSION
from app.common.api import Caller, account_caller, authenticated, get_container
from app.container import Container
from app.profiles.service import PRIVACY_VERSION, TERMS_VERSION

router = APIRouter(prefix="/v1")


class BootstrapRequest(BaseModel):
    client_time_ms: int | None = None
    app_version: str | None = None
    platform: str | None = None


@router.post("/session/bootstrap")
async def bootstrap(body: BootstrapRequest, caller: Caller = Depends(account_caller),
                    c: Container = Depends(get_container)) -> dict:
    """Safe session data only: never answer keys, raw config, bot plans, risk scores or moderation notes."""
    server_now = c.clock.now_ms()
    config = await c.config.get()
    runtime = current(await c.store.get(runtime_path(caller.uid)), caller.uid, server_now)
    entitlement = await c.store.get(f"purchase_entitlements/{caller.uid}")
    profile = c.profiles.own_profile(caller.user, entitlement) if caller.user else None
    return {
        "schema_version": 1,
        "server_time_ms": server_now,
        # Non-authoritative, for local countdown rendering only.
        "clock_offset_estimate_ms": (server_now - body.client_time_ms) if body.client_time_ms else None,
        "account": {
            "exists": caller.user is not None,
            "status": (caller.user or {}).get("status", "ACTIVE"),
            "onboarding": profile["onboarding"] if profile else
            {"consent": False, "username": False, "avatar": False, "rename_required": False},
        },
        "profile": profile,
        "runtime": pointer(runtime),
        "features": {
            "survival": config.features.survival_enabled,
            "category_queues": config.features.category_queues_enabled,
            "category_queue_ids": config.features.category_queues_for(
                (caller.user or {}).get("question_language", "en"), c.settings.region),
            "rewarded_xp": config.features.rewarded_offers_enabled,
        },
        "question_languages": config.features.competitive_languages,
        "ui_languages": config.features.ui_languages,
        "config_version": config.config_version,
        "catalog_versions": {"avatars": CATALOG_VERSION, "reactions": CATALOG_VERSION, "frames": CATALOG_VERSION,
                             "badges": CATALOG_VERSION},
        "legal": {"terms_version": TERMS_VERSION, "privacy_version": PRIVACY_VERSION},
    }


@router.get("/client-config")
async def client_config(caller: Caller = Depends(authenticated), c: Container = Depends(get_container)) -> dict:
    config = await c.config.get()
    return {
        "schema_version": 1,
        "config_version": config.config_version,
        "quick": {"questions": config.quick.normal_questions, "seconds": config.quick.seconds,
                  "wrong_penalty": config.quick.wrong_penalty, "no_answer_penalty": config.quick.no_answer_penalty,
                  "rematch_window_ms": config.quick.rematch_window_ms},
        "survival": {"seconds": config.survival.seconds, "rescue_seconds": config.survival.rescue_seconds},
        "ping_bands_ms": config.matchmaking.ping_bands_ms,
        "interstitial_min_interval_s": config.economy.interstitial_min_interval_s,
        "reaction_display_ms": 1800,
        "rewarded_xp_enabled": config.features.rewarded_offers_enabled,
        "survival_enabled": config.features.survival_enabled,
        "category_queues": {lang: config.features.category_queues_for(lang, c.settings.region)
                            for lang in config.features.competitive_languages},
        "question_languages": config.features.competitive_languages,
        "ui_languages": config.features.ui_languages,
        # Client connects only to its current match shard, selected by match_index (spec §14.1).
        "rtdb_shards": {sid: c.settings.shard_url(sid) for sid in c.settings.shard_ids},
    }
