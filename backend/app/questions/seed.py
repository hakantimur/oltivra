"""Seed content import.

Usage: ``python -m app.questions.seed [--status ACTIVE|VALIDATION_PENDING]`` (uses OLTIVRA_* settings).
Outside dev/test, seed content is imported as VALIDATION_PENDING so a human reviewer verifies it
before it can enter the competitive pool (spec §11.1).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from app.common.ids import sha256_hex
from app.common.media import MediaObjectExists
from app.questions.models import (
    IMMUTABLE_CACHE_CONTROL,
    MediaAsset,
    OptionText,
    QuestionStatus,
    question_media_path,
    webp_dimensions,
)
from app.questions.repository import QuestionRepository, TranslationInput
from app.questions.taxonomy import CATEGORIES

SEED_ROOT = Path(__file__).resolve().parents[2] / "seed"
SEED_DIR = SEED_ROOT / "questions"
# Curated questions (spec §9.1): most carry a WebP under seed/media referenced by `media.file`; some are text-only.
MEDIA_SEED_DIR = SEED_ROOT / "media_questions"
MEDIA_FILES_DIR = SEED_ROOT / "media"
SEED_LANGUAGES = ("en", "tr")


def load_seed_items(directory: Path = SEED_DIR) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        items.extend(json.loads(path.read_text(encoding="utf-8")))
    return items


def load_media_seed_items(directory: Path = MEDIA_SEED_DIR) -> list[dict[str, Any]]:
    return load_seed_items(directory)


def seed_group_id(key: str) -> str:
    """Stable ID so re-running the import is idempotent."""
    return "seed_" + sha256_hex(key)[:20]


async def import_seed(repo: QuestionRepository, store, status: QuestionStatus, actor_uid: str = "seed-import",
                      items: list[dict[str, Any]] | None = None, uploader=None,
                      media_items: list[dict[str, Any]] | None = None, now_ms: int = 0) -> dict[str, int]:
    """Import text questions and, when a media ``uploader`` is given, the image questions as well."""
    items = items if items is not None else load_seed_items()
    created = skipped = 0
    for category in CATEGORIES:
        await store.set(f"categories/{category.id}", {
            "schema_version": 1, "id": category.id, "names": category.names, "icon": category.icon,
            "subcategories": category.subcategories,
        })
    for item in items:
        if await _create(repo, item, status, actor_uid):
            created += 1
        else:
            skipped += 1
    if uploader is not None:
        media_items = media_items if media_items is not None else load_media_seed_items()
        for item in media_items:
            if await repo.get_group(seed_group_id(item["key"])):
                skipped += 1
                continue
            asset_id = await _upload_media(repo, uploader, item, status, now_ms) if item.get("media") else None
            await _create(repo, item, status, actor_uid, media_asset_id=asset_id)
            created += 1
    return {"created": created, "skipped": skipped}


async def _upload_media(repo: QuestionRepository, uploader, item: dict[str, Any], status: QuestionStatus,
                        now_ms: int) -> str:
    meta = item["media"]
    data = (MEDIA_FILES_DIR / meta["file"]).read_bytes()
    size = webp_dimensions(data)
    if size is None:
        raise ValueError(f"{item['key']}: {meta['file']} is not a readable WebP image")
    group_id = seed_group_id(item["key"])
    path = question_media_path(group_id, 1)
    try:
        await uploader.put(path, data, "image/webp", cache_control=IMMUTABLE_CACHE_CONTROL)
    except MediaObjectExists:
        pass  # re-run after a partial import: the immutable object is already stored
    asset = MediaAsset(
        id="seedmedia_" + sha256_hex(item["key"])[:20], storage_path=path, width=size[0], height=size[1],
        bytes=len(data), alt_text=meta.get("alt_text", {}), source=meta["source"], author=meta.get("author"),
        license=meta["license"], attribution=meta.get("attribution"), copyright_status=meta["copyright_status"],
        # Active seed content is dev/test only; elsewhere a human reviews the image with the question.
        review_status="APPROVED" if status == QuestionStatus.ACTIVE else "PENDING",
        question_group_id=group_id, question_version=1, created_at_ms=now_ms)
    await repo.put_media(asset)
    return asset.id


async def _create(repo: QuestionRepository, item: dict[str, Any], status: QuestionStatus, actor_uid: str,
                  media_asset_id: str | None = None) -> bool:
    group_id = seed_group_id(item["key"])
    if await repo.get_group(group_id):
        return False
    translations = [
        TranslationInput(
            language=lang,
            question_text=item["question"][lang],
            options=[OptionText(concept_id=o["concept_id"], text=o[lang]) for o in item["options"]],
            verified=status == QuestionStatus.ACTIVE,
        )
        for lang in SEED_LANGUAGES
        if lang in item["question"]
    ]
    await repo.create_question(
        category_id=item["category_id"], subcategory_id=item["subcategory_id"], difficulty=item["difficulty"],
        global_relevance_score=item["global_relevance_score"], canonical_language="en",
        translations=translations, correct_concept_id=item["correct"], source_refs=[item["source"]],
        actor_uid=actor_uid, status=status, time_sensitive=item.get("time_sensitive", False),
        media_asset_id=media_asset_id, group_id=group_id, extra={"seed_key": item["key"]},
    )
    return True


async def _main() -> None:
    from app.common.settings import Settings
    from app.container import Container

    parser = argparse.ArgumentParser()
    parser.add_argument("--status", default=None, choices=[s.value for s in QuestionStatus])
    args = parser.parse_args()
    settings = Settings()
    container = Container(settings)
    status = QuestionStatus(args.status) if args.status else (
        QuestionStatus.ACTIVE if settings.env in ("dev", "test") else QuestionStatus.VALIDATION_PENDING)
    from app.catalog.data import seed_catalogs

    await seed_catalogs(container.store)
    from app.bots.catalog import seed_bots

    await seed_bots(container.store, container.keys, container.clock.now_ms())
    result = await import_seed(container.question_repo, container.store, status,
                               uploader=container.media_uploader, now_ms=container.clock.now_ms())
    counts = await container.manifest_builder.build_all(list(SEED_LANGUAGES))
    print(json.dumps({"import": result, "manifests": counts}, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
