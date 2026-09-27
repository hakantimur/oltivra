"""Internal admin API (spec §11): questions, translations, media, validation queue, duplicates, categories,
catalogs (bots, avatars, reactions), versioned server configuration, pool health and the audit log.

Every route requires the ``admin`` custom claim and, when configured (mandatory in prod), MFA. The admin web
app only ever talks to these endpoints; no privileged credentials live in browser code.
"""

from __future__ import annotations

import base64
import binascii
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from app.common.api import Caller, get_container
from app.common.errors import ApiError, ErrorCode
from app.common.ids import new_uuid
from app.common.media import MediaObjectExists
from app.common.server_config import GameConfig
from app.common.store.docstore import Query as DocQuery
from app.container import Container
from app.questions.models import (
    IMMUTABLE_CACHE_CONTROL,
    MEDIA_EDITABLE_STATUSES,
    MediaAsset,
    OptionText,
    QuestionStatus,
    is_webp,
    media_warnings,
    question_media_path,
)
from app.questions.repository import TranslationInput

router = APIRouter(prefix="/admin/v1", tags=["admin"])

MAX_MEDIA_BYTES = 2 * 1024 * 1024


async def admin_caller(request: Request, c: Container = Depends(get_container)) -> Caller:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise ApiError(ErrorCode.UNAUTHENTICATED)
    token = await c.token_verifier.verify(header.removeprefix("Bearer ").strip())
    if not token.is_admin:
        raise ApiError(ErrorCode.FORBIDDEN, detail={"reason": "admin_required"})
    if c.settings.admin_require_mfa and not token.used_mfa:
        raise ApiError(ErrorCode.FORBIDDEN, detail={"reason": "mfa_required"})
    return Caller(token.uid, token)


# ---------------------------------------------------------------------------------------------- models


class OptionIn(BaseModel):
    concept_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    text: str = Field(min_length=1, max_length=120)


class TranslationIn(BaseModel):
    language: str = Field(min_length=2, max_length=8)
    question_text: str = Field(min_length=5, max_length=300)
    options: list[OptionIn] = Field(min_length=4, max_length=4)
    verified: bool = False

    def to_input(self) -> TranslationInput:
        return TranslationInput(self.language, self.question_text,
                                [OptionText(concept_id=o.concept_id, text=o.text) for o in self.options], self.verified)


class QuestionIn(BaseModel):
    category_id: str
    subcategory_id: str
    difficulty: Literal["EASY", "MEDIUM", "HARD"]
    global_relevance_score: int = Field(ge=1, le=5)
    canonical_language: str = "en"
    translations: list[TranslationIn] = Field(min_length=1)
    correct_concept_id: str
    source_refs: list[str] = Field(default_factory=list, max_length=10)
    time_sensitive: bool = False
    review_after_ms: int | None = None
    media_asset_id: str | None = None
    status: Literal["DRAFT", "VALIDATION_PENDING"] = "DRAFT"


class VersionIn(BaseModel):
    translations: list[TranslationIn] = Field(min_length=1)
    correct_concept_id: str
    source_refs: list[str] = Field(default_factory=list, max_length=10)
    changes: dict[str, Any] = Field(default_factory=dict)


class TransitionIn(BaseModel):
    target: QuestionStatus
    reason: str = Field(min_length=3, max_length=500)


class MediaIn(BaseModel):
    # Question media is always the draft version's single WebP image (spec §9.1, §34.1).
    question_group_id: str = Field(min_length=1, max_length=64)
    version: int = Field(ge=1)
    content_type: Literal["image/webp"]
    data_base64: str
    width: int = Field(ge=64, le=4096)
    height: int = Field(ge=64, le=4096)
    alt_text: dict[str, str] = Field(default_factory=dict)
    source: str = Field(min_length=2, max_length=300)
    author: str | None = None
    license: str = Field(min_length=2, max_length=120)
    attribution: str | None = None
    copyright_status: Literal["CLEARED", "PUBLIC_DOMAIN", "LICENSED", "PENDING"]


class MediaReviewIn(BaseModel):
    review_status: Literal["APPROVED", "REJECTED", "PENDING"]
    reason: str = Field(default="", max_length=300)


class CategoryIn(BaseModel):
    names: dict[str, str] | None = None
    subcategories: dict[str, dict[str, str]] | None = None
    disabled_subcategories: list[str] | None = None


class DuplicateCheckIn(BaseModel):
    question_text: str
    options: list[OptionIn] | None = None
    correct_concept_id: str | None = None
    language: str = "en"
    exclude_group_id: str | None = None


class BotIn(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=16)
    avatar_id: str | None = None
    profile: Literal["BEGINNER", "NORMAL", "STRONG", "EXPERT"] | None = None
    active: bool | None = None


class AvatarIn(BaseModel):
    motif: str | None = None
    bg: str | None = None
    fg: str | None = None
    accent: str | None = None
    active: bool | None = None
    sort: int | None = None


class ReactionIn(BaseModel):
    kind: Literal["EMOJI", "TEXT"] | None = None
    display: str | None = Field(default=None, max_length=16)
    labels: dict[str, str] | None = None
    active: bool | None = None


class ConfigIn(BaseModel):
    config: dict[str, Any]
    reason: str = Field(min_length=3, max_length=500)


async def _rebuild_manifests(c: Container) -> None:
    config = await c.config.get()
    languages = sorted(set(config.features.competitive_languages) | set(config.features.ui_languages))
    await c.manifest_builder.build_all(languages)
    c.manifest_cache.invalidate()
    c.duplicates.invalidate()


# ---------------------------------------------------------------------------------------------- questions


@router.get("/questions")
async def list_questions(status: QuestionStatus | None = None, category_id: str | None = None,
                         difficulty: str | None = None, q: str | None = Query(default=None, max_length=100),
                         language: str = "en", limit: int = Query(default=50, ge=1, le=200),
                         offset: int = Query(default=0, ge=0), caller: Caller = Depends(admin_caller),
                         c: Container = Depends(get_container)) -> dict:
    query = DocQuery("question_groups")
    if status:
        query = query.filter("status", "==", status.value)
    if category_id:
        query = query.filter("category_id", "==", category_id)
    if difficulty:
        query = query.filter("declared_difficulty", "==", difficulty)
    rows = await c.store.query(query.order("qid", "desc"))
    if q:
        needle = q.lower()
        texts = {e.gid: e.text for e in await c.duplicates._entries(language)}
        rows = [r for r in rows if needle in (texts.get(r.id) or "").lower() or needle in r.id]
    page = rows[offset:offset + limit]
    paths = [f"question_translations/{r.id}_{language}_{r.data['version']}" for r in page]
    translations = await c.store.get_many(paths) if paths else []
    items = []
    for row, translation in zip(page, translations, strict=True):
        data = row.data
        items.append({"question_group_id": row.id, "qid": data["qid"], "status": data["status"],
                      "version": data["version"], "category_id": data["category_id"],
                      "subcategory_id": data["subcategory_id"], "difficulty": data["declared_difficulty"],
                      "global_relevance_score": data.get("global_relevance_score"),
                      "languages": data.get("languages", []), "text": (translation or {}).get("question_text"),
                      "has_media": bool(data.get("media_asset_id")), "ai": data.get("ai"),
                      "updated_at_ms": data.get("updated_at_ms")})
    return {"schema_version": 1, "total": len(rows), "items": items,
            "next_offset": offset + limit if offset + limit < len(rows) else None}


@router.get("/questions/{group_id}")
async def get_question(group_id: str, caller: Caller = Depends(admin_caller),
                       c: Container = Depends(get_container)) -> dict:
    group = await c.question_repo.get_group(group_id)
    if not group:
        raise ApiError(ErrorCode.NOT_FOUND)
    version = group["version"]
    languages = group.get("languages") or [group.get("canonical_language", "en")]
    translations = await c.store.get_many([f"question_translations/{group_id}_{lang}_{version}"
                                           for lang in languages])
    private = await c.store.get(f"question_private/{group_id}_{version}")
    history = await c.store.query(DocQuery("question_status_history").filter("question_group_id", "==", group_id)
                                  .order("at_ms", "desc").take(50))
    versions = await c.store.query(DocQuery("question_versions").filter("question_group_id", "==", group_id)
                                   .order("version", "desc"))
    counter = await c.store.get(f"question_report_counters/{group_id}_{version}")
    media = await c.store.get(f"media_assets/{group['media_asset_id']}") if group.get("media_asset_id") else None
    stats = {}
    for lang in languages:
        for mode in ("QUICK", "SURVIVAL", "SYNOVA"):
            key = f"{group_id}_{version}_{lang}_{mode}"
            summary = await c.store.get(f"question_stats_summaries/{key}")
            if summary:
                stats[f"{lang}_{mode}"] = summary
    return {"schema_version": 1, "group": group, "translations": [t for t in translations if t],
            "private": private, "status_history": [h.data for h in history],
            "versions": [{"version": v.data["version"], "created_at_ms": v.data["created_at_ms"]} for v in versions],
            "reports": counter, "media": media, "stats": stats}


@router.post("/questions")
async def create_question(body: QuestionIn, caller: Caller = Depends(admin_caller),
                          c: Container = Depends(get_container)) -> dict:
    if body.category_id not in {cat["id"] for cat in await c.categories.all()}:
        raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "unknown_category"})
    canonical = next((t for t in body.translations if t.language == body.canonical_language), None)
    duplicates = await c.duplicates.candidates(
        question_text=canonical.question_text if canonical else body.translations[0].question_text,
        options=[o.model_dump() for o in (canonical or body.translations[0]).options],
        correct_concept_id=body.correct_concept_id, language=body.canonical_language)
    group = await c.question_repo.create_question(
        category_id=body.category_id, subcategory_id=body.subcategory_id, difficulty=body.difficulty,
        global_relevance_score=body.global_relevance_score, canonical_language=body.canonical_language,
        translations=[t.to_input() for t in body.translations], correct_concept_id=body.correct_concept_id,
        source_refs=body.source_refs, actor_uid=caller.uid, status=QuestionStatus(body.status),
        time_sensitive=body.time_sensitive, review_after_ms=body.review_after_ms,
        media_asset_id=body.media_asset_id, extra={"created_by": caller.uid})
    c.duplicates.invalidate()
    await c.audit.record(actor=caller.uid, action="QUESTION_CREATE", subject=f"question:{group['id']}")
    return {"schema_version": 1, "group": group, "duplicates": duplicates}


@router.post("/questions/{group_id}/versions")
async def new_version(group_id: str, body: VersionIn, caller: Caller = Depends(admin_caller),
                      c: Container = Depends(get_container)) -> dict:
    allowed = {"category_id", "subcategory_id", "declared_difficulty", "global_relevance_score", "time_sensitive",
               "review_after_ms", "media_asset_id"}
    if set(body.changes) - allowed:
        raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "unsupported_change"})
    group = await c.question_repo.new_version(group_id, translations=[t.to_input() for t in body.translations],
                                              correct_concept_id=body.correct_concept_id,
                                              source_refs=body.source_refs, actor_uid=caller.uid,
                                              changes=body.changes)
    await _rebuild_manifests(c)  # the old active version leaves the pool until the new one is verified
    await c.audit.record(actor=caller.uid, action="QUESTION_NEW_VERSION", subject=f"question:{group_id}",
                         detail={"version": group["version"]})
    return {"schema_version": 1, "group": group}


@router.post("/questions/{group_id}/transition")
async def transition(group_id: str, body: TransitionIn, caller: Caller = Depends(admin_caller),
                     c: Container = Depends(get_container)) -> dict:
    group = await c.question_repo.transition(group_id, body.target, caller.uid, body.reason)
    if body.target in (QuestionStatus.VERIFIED, QuestionStatus.ACTIVE):
        private_path = f"question_private/{group_id}_{group['version']}"
        await c.store.update(private_path, {"verified_by": caller.uid, "verified_at_ms": c.clock.now_ms()})
    await _rebuild_manifests(c)
    await c.audit.record(actor=caller.uid, action=f"QUESTION_{body.target.value}", subject=f"question:{group_id}",
                         reason_code=body.reason, reversible=body.target != QuestionStatus.RETIRED)
    return {"schema_version": 1, "group": group}


@router.put("/questions/{group_id}/translations/{language}")
async def upsert_translation(group_id: str, language: str, body: TranslationIn,
                             caller: Caller = Depends(admin_caller), c: Container = Depends(get_container)) -> dict:
    if body.language != language:
        raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "language_mismatch"})
    translation = await c.question_repo.upsert_translation(group_id, body.to_input())
    await c.audit.record(actor=caller.uid, action="TRANSLATION_UPSERT", subject=f"question:{group_id}",
                         detail={"language": language})
    return {"schema_version": 1, "translation": translation}


@router.post("/questions/{group_id}/translations/{language}/verify")
async def verify_translation(group_id: str, language: str, verified: bool = True,
                             caller: Caller = Depends(admin_caller), c: Container = Depends(get_container)) -> dict:
    group = await c.question_repo.get_group(group_id)
    if not group:
        raise ApiError(ErrorCode.NOT_FOUND)
    await c.question_repo.mark_translation_verified(group_id, group["version"], language, verified)
    await _rebuild_manifests(c)
    await c.audit.record(actor=caller.uid, action="TRANSLATION_VERIFY", subject=f"question:{group_id}",
                         detail={"language": language, "verified": verified})
    return {"schema_version": 1, "verified": verified}


@router.get("/validation-queue")
async def validation_queue(limit: int = Query(default=50, ge=1, le=200), caller: Caller = Depends(admin_caller),
                           c: Container = Depends(get_container)) -> dict:
    items = []
    for status in (QuestionStatus.VALIDATION_PENDING, QuestionStatus.GENERATED):
        rows = await c.store.query(DocQuery("question_groups").filter("status", "==", status.value).take(limit))
        items += [{"question_group_id": r.id, "status": r.data["status"], "category_id": r.data["category_id"],
                   "difficulty": r.data["declared_difficulty"], "version": r.data["version"], "ai": r.data.get("ai"),
                   "updated_at_ms": r.data.get("updated_at_ms")} for r in rows]
    return {"schema_version": 1, "items": items[:limit]}


@router.post("/duplicates/check")
async def duplicate_check(body: DuplicateCheckIn, caller: Caller = Depends(admin_caller),
                          c: Container = Depends(get_container)) -> dict:
    return {"schema_version": 1, **await c.duplicates.candidates(
        question_text=body.question_text, options=[o.model_dump() for o in body.options] if body.options else None,
        correct_concept_id=body.correct_concept_id, language=body.language, exclude_gid=body.exclude_group_id)}


# ---------------------------------------------------------------------------------------------- media


@router.post("/media")
async def upload_media(body: MediaIn, caller: Caller = Depends(admin_caller),
                       c: Container = Depends(get_container)) -> dict:
    try:
        data = base64.b64decode(body.data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "base64"}) from exc
    if not data or len(data) > MAX_MEDIA_BYTES:
        raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "size", "max_bytes": MAX_MEDIA_BYTES})
    if not is_webp(data):
        raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "not_webp"})
    group = await c.question_repo.get_group(body.question_group_id)
    if not group:
        raise ApiError(ErrorCode.NOT_FOUND)
    if group["version"] != body.version or group["status"] not in MEDIA_EDITABLE_STATUSES:
        # Verified/active versions are immutable: edit by creating a new version first.
        raise ApiError(ErrorCode.CONFLICT, detail={"reason": "version_immutable", "current_version": group["version"]})
    path = question_media_path(body.question_group_id, body.version)
    try:
        await c.media_uploader.put(path, data, body.content_type, cache_control=IMMUTABLE_CACHE_CONTROL)
    except MediaObjectExists as exc:
        raise ApiError(ErrorCode.CONFLICT, detail={"reason": "media_exists"}) from exc
    warnings = media_warnings(len(data), body.width, body.height)
    asset = MediaAsset(id=new_uuid(), storage_path=path, content_type=body.content_type, width=body.width,
                       height=body.height, bytes=len(data), alt_text=body.alt_text, source=body.source,
                       author=body.author, license=body.license, attribution=body.attribution,
                       copyright_status=body.copyright_status, review_status="PENDING",
                       question_group_id=body.question_group_id, question_version=body.version,
                       preferred_limits_ok=not warnings, created_at_ms=c.clock.now_ms())
    await c.question_repo.put_media(asset)
    await c.question_repo.attach_media(body.question_group_id, body.version, asset.id)
    await c.audit.record(actor=caller.uid, action="MEDIA_UPLOAD", subject=f"media:{asset.id}")
    return {"schema_version": 1, "media": asset.model_dump(), "warnings": warnings}


@router.get("/media")
async def list_media(review_status: str | None = None, caller: Caller = Depends(admin_caller),
                     c: Container = Depends(get_container)) -> dict:
    query = DocQuery("media_assets")
    if review_status:
        query = query.filter("review_status", "==", review_status)
    return {"schema_version": 1, "items": [r.data for r in await c.store.query(query.take(200))]}


@router.patch("/media/{asset_id}")
async def review_media(asset_id: str, body: MediaReviewIn, caller: Caller = Depends(admin_caller),
                       c: Container = Depends(get_container)) -> dict:
    if not await c.store.get(f"media_assets/{asset_id}"):
        raise ApiError(ErrorCode.NOT_FOUND)
    await c.store.update(f"media_assets/{asset_id}", {"review_status": body.review_status,
                                                      "reviewed_by": caller.uid,
                                                      "reviewed_at_ms": c.clock.now_ms()})
    await _rebuild_manifests(c)
    await c.audit.record(actor=caller.uid, action=f"MEDIA_{body.review_status}", subject=f"media:{asset_id}",
                         reason_code=body.reason)
    return {"schema_version": 1, "media": await c.store.get(f"media_assets/{asset_id}")}


# ---------------------------------------------------------------------------------------------- categories


@router.get("/categories")
async def admin_categories(caller: Caller = Depends(admin_caller), c: Container = Depends(get_container)) -> dict:
    return {"schema_version": 1, "categories": await c.categories.all()}


@router.put("/categories/{category_id}")
async def update_category(category_id: str, body: CategoryIn, caller: Caller = Depends(admin_caller),
                          c: Container = Depends(get_container)) -> dict:
    category = await c.categories.update(category_id, names=body.names, subcategories=body.subcategories,
                                         disabled=body.disabled_subcategories, now_ms=c.clock.now_ms())
    await c.audit.record(actor=caller.uid, action="CATEGORY_UPDATE", subject=f"category:{category_id}")
    return {"schema_version": 1, "category": category}


# ---------------------------------------------------------------------------------------------- catalogs


@router.get("/bots")
async def list_bots(caller: Caller = Depends(admin_caller), c: Container = Depends(get_container)) -> dict:
    rows = await c.store.query(DocQuery("bot_profiles"))
    return {"schema_version": 1, "bots": sorted((r.data for r in rows), key=lambda b: b["bot_id"]),
            "profiles": {k: v.model_dump() for k, v in (await c.config.get()).bots.profiles.items()}}


@router.put("/bots/{bot_id}")
async def upsert_bot(bot_id: str, body: BotIn, caller: Caller = Depends(admin_caller),
                     c: Container = Depends(get_container)) -> dict:
    from app.bots.catalog import bot_public_profile
    from app.usernames.rules import check_username, normalize

    current = await c.store.get(f"bot_profiles/{bot_id}") or {"schema_version": 1, "bot_id": bot_id,
                                                             "active": True, "profile": "NORMAL"}
    updated = {**current, **{k: v for k, v in body.model_dump().items() if v is not None}}
    if not updated.get("username") or not updated.get("avatar_id"):
        raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "username_and_avatar_required"})
    if updated["avatar_id"] not in {a["id"] for a in await c.catalog.avatars()}:
        raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "unknown_avatar"})
    now = c.clock.now_ms()
    if body.username and body.username.lower() != (current.get("username") or "").lower():
        if check_username(body.username):
            raise ApiError(ErrorCode.USERNAME_INVALID)
        norm = normalize(body.username)
        # Bot usernames are reserved in the same registry as human usernames (spec §23.1).
        if await c.store.get(f"username_registry/{norm}"):
            raise ApiError(ErrorCode.USERNAME_TAKEN)
        await c.store.set(f"username_registry/{norm}", {"schema_version": 1, "state": "ACTIVE",
                                                        "uid": f"bot:{bot_id}", "is_bot": True, "name": norm,
                                                        "updated_at_ms": now})
        if current.get("username"):
            await c.store.delete(f"username_registry/{normalize(current['username'])}")
    await c.store.set(f"bot_profiles/{bot_id}", updated)
    profile = bot_public_profile(c.keys, updated, await c.config.get())
    await c.store.set(f"public_profiles/{profile['public_id']}", profile)
    await c.store.set(f"public_ids/{profile['public_id']}", {"uid": f"bot:{bot_id}", "is_bot": True})
    await c.audit.record(actor=caller.uid, action="BOT_UPSERT", subject=f"bot:{bot_id}")
    return {"schema_version": 1, "bot": updated}


@router.put("/avatars/{avatar_id}")
async def upsert_avatar(avatar_id: str, body: AvatarIn, caller: Caller = Depends(admin_caller),
                        c: Container = Depends(get_container)) -> dict:
    current = await c.store.get(f"avatar_catalog/{avatar_id}") or {"schema_version": 1, "id": avatar_id,
                                                                   "active": True, "sort": 999}
    updated = {**current, **{k: v for k, v in body.model_dump().items() if v is not None}}
    if not all(updated.get(k) for k in ("motif", "bg", "fg", "accent")):
        raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "incomplete_avatar"})
    await c.store.set(f"avatar_catalog/{avatar_id}", updated)
    await _bump_catalog(c, "avatars")
    await c.audit.record(actor=caller.uid, action="AVATAR_UPSERT", subject=f"avatar:{avatar_id}")
    return {"schema_version": 1, "avatar": updated}


@router.put("/reactions/{reaction_id}")
async def upsert_reaction(reaction_id: str, body: ReactionIn, caller: Caller = Depends(admin_caller),
                          c: Container = Depends(get_container)) -> dict:
    current = await c.store.get(f"reaction_catalog/{reaction_id}") or {"schema_version": 1, "id": reaction_id,
                                                                       "active": True}
    updated = {**current, **{k: v for k, v in body.model_dump().items() if v is not None}}
    if not updated.get("display") or not updated.get("labels") or not updated.get("kind"):
        raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "incomplete_reaction"})
    await c.store.set(f"reaction_catalog/{reaction_id}", updated)
    await _bump_catalog(c, "reactions")
    await c.audit.record(actor=caller.uid, action="REACTION_UPSERT", subject=f"reaction:{reaction_id}")
    return {"schema_version": 1, "reaction": updated}


async def _bump_catalog(c: Container, key: str) -> None:
    from app.common.store.docstore import Increment

    await c.store.set("catalog_meta/versions", {key: Increment(1)}, merge=True)
    c.catalog.invalidate()


# ---------------------------------------------------------------------------------------------- config


@router.get("/config")
async def get_config(caller: Caller = Depends(admin_caller), c: Container = Depends(get_container)) -> dict:
    config = await c.config.get()
    rows = await c.store.query(DocQuery("server_config").order("config_version", "desc").take(20))
    return {"schema_version": 1, "active": config.model_dump(),
            "versions": [{"config_version": r.data.get("config_version"), "published_by": r.data.get("published_by"),
                          "published_at_ms": r.data.get("published_at_ms"), "reason": r.data.get("reason")}
                         for r in rows if r.id.startswith("v")]}


@router.post("/config")
async def publish_config(body: ConfigIn, caller: Caller = Depends(admin_caller),
                         c: Container = Depends(get_container)) -> dict:
    try:
        candidate = GameConfig.model_validate({**(await c.config.get()).model_dump(), **body.config})
    except ValueError as exc:
        raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "invalid_config", "error": str(exc)[:500]}) \
            from exc
    published = await c.config.publish(candidate, caller.uid, c.clock.now_ms())
    await c.store.update(f"server_config/v{published.config_version}", {"reason": body.reason})
    await c.audit.record(actor=caller.uid, action="CONFIG_PUBLISH", subject=f"config:v{published.config_version}",
                         reason_code=body.reason)
    return {"schema_version": 1, "config_version": published.config_version}


# ---------------------------------------------------------------------------------------------- health & audit


@router.get("/pool-health")
async def pool_health(language: str = "en", trials: int = Query(default=200, ge=10, le=2000),
                      caller: Caller = Depends(admin_caller), c: Container = Depends(get_container)) -> dict:
    return await c.pool_health.report(language, trials)


@router.post("/manifests/rebuild")
async def rebuild_manifests(caller: Caller = Depends(admin_caller), c: Container = Depends(get_container)) -> dict:
    await _rebuild_manifests(c)
    await c.audit.record(actor=caller.uid, action="MANIFEST_REBUILD", subject="manifests")
    return {"schema_version": 1, "rebuilt": True}


@router.get("/audit")
async def audit(subject: str | None = None, actor: str | None = None, limit: int = Query(default=50, ge=1, le=200),
                caller: Caller = Depends(admin_caller), c: Container = Depends(get_container)) -> dict:
    return {"schema_version": 1, "entries": await c.audit.list(subject=subject, actor=actor, limit=limit)}


# ---------------------------------------------------------------------------------------------- AI generation


class AiJobIn(BaseModel):
    category_id: str
    subcategory_id: str
    difficulty: Literal["EASY", "MEDIUM", "HARD"]
    canonical_language: str = "en"
    required_languages: list[str] = Field(default_factory=list, max_length=12)
    count: int = Field(ge=1, le=100)
    min_global_relevance: int = Field(default=4, ge=1, le=5)
    media_required: bool = False


@router.post("/ai-jobs")
async def create_ai_job(body: AiJobIn, caller: Caller = Depends(admin_caller),
                        c: Container = Depends(get_container)) -> dict:
    from app.admin.ai_generation import GenerationSpec

    job = await c.ai_generation.create_job(caller.uid, GenerationSpec(**body.model_dump()))
    return {"schema_version": 1, "job": job}


@router.get("/ai-jobs")
async def list_ai_jobs(limit: int = Query(default=50, ge=1, le=200), caller: Caller = Depends(admin_caller),
                       c: Container = Depends(get_container)) -> dict:
    rows = await c.store.query(DocQuery("ai_generation_jobs").order("created_at_ms", "desc").take(limit))
    return {"schema_version": 1, "items": [
        {k: r.data.get(k) for k in ("job_id", "status", "spec", "provider", "model", "prompt_version",
                                    "created_by", "created_at_ms", "completed_at_ms", "attempts", "error")}
        | {"accepted": len(r.data.get("accepted") or []), "rejected": len(r.data.get("rejected") or [])}
        for r in rows]}


@router.get("/ai-jobs/{job_id}")
async def get_ai_job(job_id: str, caller: Caller = Depends(admin_caller), c: Container = Depends(get_container)
                     ) -> dict:
    job = await c.store.get(f"ai_generation_jobs/{job_id}")
    if not job:
        raise ApiError(ErrorCode.NOT_FOUND)
    return {"schema_version": 1, "job": job}


@router.post("/ai-jobs/{job_id}/retry")
async def retry_ai_job(job_id: str, caller: Caller = Depends(admin_caller), c: Container = Depends(get_container)
                       ) -> dict:
    return {"schema_version": 1, "job": await c.ai_generation.retry(job_id, caller.uid)}
