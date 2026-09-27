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
from app.questions.models import OptionText, QuestionStatus
from app.questions.repository import QuestionRepository, TranslationInput
from app.questions.taxonomy import CATEGORIES

SEED_DIR = Path(__file__).resolve().parents[2] / "seed" / "questions"
SEED_LANGUAGES = ("en", "tr")


def load_seed_items(directory: Path = SEED_DIR) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        items.extend(json.loads(path.read_text(encoding="utf-8")))
    return items


def seed_group_id(key: str) -> str:
    """Stable ID so re-running the import is idempotent."""
    return "seed_" + sha256_hex(key)[:20]


async def import_seed(repo: QuestionRepository, store, status: QuestionStatus, actor_uid: str = "seed-import",
                      items: list[dict[str, Any]] | None = None) -> dict[str, int]:
    items = items if items is not None else load_seed_items()
    created = skipped = 0
    for category in CATEGORIES:
        await store.set(f"categories/{category.id}", {
            "schema_version": 1, "id": category.id, "names": category.names, "icon": category.icon,
            "subcategories": category.subcategories,
        })
    for item in items:
        group_id = seed_group_id(item["key"])
        if await repo.get_group(group_id):
            skipped += 1
            continue
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
            group_id=group_id, extra={"seed_key": item["key"]},
        )
        created += 1
    return {"created": created, "skipped": skipped}


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
    result = await import_seed(container.question_repo, container.store, status)
    counts = await container.manifest_builder.build_all(list(SEED_LANGUAGES))
    print(json.dumps({"import": result, "manifests": counts}, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
