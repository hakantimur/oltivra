"""Onboarding, profile, username, avatar, preferences and catalog endpoints (spec §27.1–27.2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from app.common import rate_limit
from app.common.api import Caller, account_caller, authenticated, get_container, player, run_mutation
from app.container import Container

router = APIRouter(prefix="/v1")


class ConsentRequest(BaseModel):
    request_id: str
    age_gate_confirmed: bool
    terms_version: str = Field(max_length=16)
    privacy_version: str = Field(max_length=16)


class UsernameRequest(BaseModel):
    request_id: str
    username: str = Field(max_length=32)


class AvatarRequest(BaseModel):
    request_id: str
    avatar_id: str = Field(max_length=32)


class PreferencesRequest(BaseModel):
    request_id: str
    question_language: str | None = Field(default=None, max_length=16)
    ui_language: str | None = Field(default=None, max_length=16)
    notifications: dict[str, bool] | None = None


class EquipRequest(BaseModel):
    request_id: str
    frame_id: str | None = Field(default=None, max_length=32)
    featured_badge_ids: list[str] | None = Field(default=None, max_length=3)


async def _own(c: Container, uid: str) -> dict:
    user = await c.store.get(f"users/{uid}")
    entitlement = await c.store.get(f"purchase_entitlements/{uid}")
    return {"schema_version": 1, "profile": c.profiles.own_profile(user, entitlement)}


@router.post("/onboarding/consent")
async def consent(body: ConsentRequest, request: Request, caller: Caller = Depends(account_caller),
                  c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        await c.profiles.record_consent(caller.uid, body.age_gate_confirmed, body.terms_version, body.privacy_version)
        return await _own(c, caller.uid)

    return await run_mutation(c, request, caller, "onboarding.consent", body.model_dump(), handler)


@router.get("/profile")
async def get_profile(caller: Caller = Depends(account_caller), c: Container = Depends(get_container)) -> dict:
    if not caller.user:
        from app.common.errors import ApiError, ErrorCode

        raise ApiError(ErrorCode.PROFILE_INCOMPLETE, detail={"reason": "consent_required"})
    return await _own(c, caller.uid)


@router.get("/usernames/availability")
async def username_availability(username: str = Query(max_length=32), caller: Caller = Depends(account_caller),
                                c: Container = Depends(get_container)) -> dict:
    await c.rate_limiter.hit(rate_limit.USERNAME_SEARCH, caller.uid)
    return {"schema_version": 1, **await c.profiles.check_availability(caller.uid, username)}


@router.post("/profile/username")
async def claim_username(body: UsernameRequest, request: Request, caller: Caller = Depends(account_caller),
                         c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        await c.profiles.claim_username(caller.uid, body.username, change=False)
        return await _own(c, caller.uid)

    return await run_mutation(c, request, caller, "profile.username", body.model_dump(), handler)


@router.post("/profile/username/change")
async def change_username(body: UsernameRequest, request: Request, caller: Caller = Depends(account_caller),
                          c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        await c.profiles.claim_username(caller.uid, body.username, change=True)
        return await _own(c, caller.uid)

    return await run_mutation(c, request, caller, "profile.username.change", body.model_dump(), handler)


@router.patch("/profile/avatar")
async def set_avatar(body: AvatarRequest, request: Request, caller: Caller = Depends(account_caller),
                     c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        await c.profiles.set_avatar(caller.uid, body.avatar_id)
        return await _own(c, caller.uid)

    return await run_mutation(c, request, caller, "profile.avatar", body.model_dump(), handler)


@router.patch("/profile/preferences")
async def set_preferences(body: PreferencesRequest, request: Request, caller: Caller = Depends(account_caller),
                          c: Container = Depends(get_container)) -> dict:
    config = await c.config.get()

    async def handler() -> dict:
        await c.profiles.set_preferences(caller.uid, question_language=body.question_language,
                                         ui_language=body.ui_language, notifications=body.notifications,
                                         competitive_languages=config.features.competitive_languages,
                                         ui_languages=config.features.ui_languages)
        return await _own(c, caller.uid)

    return await run_mutation(c, request, caller, "profile.preferences", body.model_dump(), handler)


@router.patch("/profile/cosmetics")
async def equip(body: EquipRequest, request: Request, caller: Caller = Depends(player),
                c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        await c.profiles.equip(caller.uid, body.frame_id, body.featured_badge_ids)
        return await _own(c, caller.uid)

    return await run_mutation(c, request, caller, "profile.cosmetics", body.model_dump(), handler)


@router.get("/avatars")
async def avatars(caller: Caller = Depends(authenticated), c: Container = Depends(get_container)) -> dict:
    return {"schema_version": 1, "avatars": await c.catalog.avatars()}


@router.get("/reactions")
async def reactions(lang: str = Query("en", max_length=16), caller: Caller = Depends(authenticated),
                    c: Container = Depends(get_container)) -> dict:
    items = await c.catalog.reactions()
    return {"schema_version": 1, "reactions": [
        {"id": r["id"], "kind": r["kind"], "display": r["display"],
         "label": r["labels"].get(lang, r["labels"]["en"])} for r in items]}


@router.get("/cosmetics")
async def cosmetics(caller: Caller = Depends(authenticated), c: Container = Depends(get_container)) -> dict:
    return {"schema_version": 1, "frames": c.catalog.frames(), "badges": c.catalog.badges()}
