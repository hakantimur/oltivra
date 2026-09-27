"""Builds server-only question plans for a match: select from manifests, load content, re-verify, replace.

Plan items live only in the authoritative branch of the canonical match root until their round begins.
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from typing import Any

from app.common.clock import Clock
from app.manifests.manifest import ManifestCache, ManifestEntry
from app.questions.exposure import ExposureService, ExposureUnion
from app.questions.models import Difficulty, competitive_eligibility
from app.questions.repository import QuestionBundle, QuestionRepository
from app.questions.selector import InsufficientInventory, select_quick, select_survival

MAX_REPLACEMENT_ROUNDS = 6


def plan_item(entry: ManifestEntry, bundle: QuestionBundle) -> dict[str, Any]:
    translation = bundle.translation or {}
    media = None
    if bundle.media:
        media = {
            "asset_id": bundle.media["id"],
            "path": bundle.media["storage_path"],
            "aspect": round(bundle.media["width"] / max(1, bundle.media["height"]), 4),
            "alt": bundle.media.get("alt_text", {}),
        }
    return {
        "qid": entry.qid,
        "gid": entry.gid,
        "v": entry.v,
        "difficulty": entry.d,
        "category_id": entry.cat,
        "subcategory_id": entry.sub,
        "text": translation["question_text"],
        "options": [{"concept_id": o["concept_id"], "text": o["text"]} for o in translation["options"]],
        "correct": (bundle.private or {})["correct_concept_id"],
        "media": media,
    }


def bundle_problems(bundle: QuestionBundle, now_ms: int, mode: str) -> list[str]:
    problems = competitive_eligibility(bundle.group, bundle.translation, now_ms, bundle.media, mode)
    if bundle.private is None:
        problems.append("private_answer_missing")
    elif bundle.translation and bundle.private["correct_concept_id"] not in {
            o["concept_id"] for o in bundle.translation.get("options", [])}:
        problems.append("correct_not_in_options")
    if bundle.group.get("version") is not None and bundle.private and \
            bundle.private.get("question_version") != bundle.group.get("version"):
        problems.append("private_version_mismatch")
    return problems


class QuestionPlanService:
    def __init__(self, manifests: ManifestCache, repo: QuestionRepository, exposure: ExposureService,
                 clock: Clock) -> None:
        self._manifests = manifests
        self._repo = repo
        self._exposure = exposure
        self._clock = clock

    async def _pools(self, language: str, mode: str, excluded: set[str]) -> dict[Difficulty, list[ManifestEntry]]:
        pools: dict[Difficulty, list[ManifestEntry]] = {}
        for difficulty in Difficulty:
            entries = await self._manifests.get(language, mode, difficulty.value)
            pools[difficulty] = [e for e in entries if e.gid not in excluded]
        return pools

    async def _verify(self, entries: list[ManifestEntry], language: str, mode: str
                      ) -> tuple[list[dict[str, Any]], set[str]]:
        bundles = await self._repo.load_bundles([(e.gid, e.v) for e in entries], language)
        now = self._clock.now_ms()
        items: list[dict[str, Any]] = []
        bad: set[str] = set()
        for entry, bundle in zip(entries, bundles, strict=True):
            if bundle.group.get("version") != entry.v or bundle_problems(bundle, now, mode):
                bad.add(entry.gid)
            else:
                items.append(plan_item(entry, bundle))
        return items, bad

    async def quick_plan(self, language: str, human_uids: Iterable[str], seed: str,
                         exclude_gids: Iterable[str] = ()) -> dict[str, list[dict[str, Any]]]:
        union = await self._exposure.union(human_uids)
        excluded = set(exclude_gids)
        for _ in range(MAX_REPLACEMENT_ROUNDS):
            pools = await self._pools(language, "QUICK", excluded)
            normal, reserves = select_quick(pools, union, random.Random(seed + str(len(excluded))))
            normal_items, bad_normal = await self._verify(normal, language, "QUICK")
            reserve_items, bad_reserve = await self._verify(reserves, language, "QUICK")
            if not bad_normal and not bad_reserve:
                return {"normal": normal_items, "reserve": reserve_items}
            excluded |= bad_normal | bad_reserve
        raise InsufficientInventory(Difficulty.MEDIUM)

    async def survival_plan(self, language: str, human_uids: Iterable[str], seed: str,
                            exclude_gids: Iterable[str] = (), targets: dict[Difficulty, int] | None = None,
                            union: ExposureUnion | None = None) -> dict[str, list[dict[str, Any]]]:
        union = union or await self._exposure.union(human_uids)
        excluded = set(exclude_gids)
        for _ in range(MAX_REPLACEMENT_ROUNDS):
            pools = await self._pools(language, "SURVIVAL", excluded)
            picks = select_survival(pools, union, random.Random(seed + str(len(excluded))), targets)
            out: dict[str, list[dict[str, Any]]] = {}
            all_bad: set[str] = set()
            for difficulty, entries in picks.items():
                items, bad = await self._verify(entries, language, "SURVIVAL")
                out[difficulty.value] = items
                all_bad |= bad
            if not all_bad:
                if sum(len(v) for v in out.values()) == 0:
                    raise InsufficientInventory(Difficulty.EASY)
                return out
            excluded |= all_bad
        raise InsufficientInventory(Difficulty.EASY)
