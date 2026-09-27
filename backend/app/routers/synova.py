"""Synova curiosity (solo) access to the shared question platform (spec §38).

The same question versions, exposure history and human statistics serve Synova and Live Trivia;
only safe current-item payloads are returned, and correctness is decided server-side.
"""

from __future__ import annotations

import random

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.common.api import Caller, account_caller, get_container, run_mutation
from app.common.errors import ApiError, ErrorCode
from app.common.ids import new_uuid
from app.container import Container
from app.questions.models import Difficulty
from app.questions.plan import bundle_problems
from app.questions.stats import StatIntent
from app.questions.taxonomy import CATEGORY_IDS

router = APIRouter(prefix="/v1/synova")

MEDIA_TTL_MS = 5 * 60_000
MAX_ATTEMPTS = 8


class NextQuestionRequest(BaseModel):
    request_id: str
    language: str = Field("en", max_length=16)
    category_ids: list[str] = Field(default_factory=list, max_length=9)
    difficulties: list[Difficulty] = Field(default_factory=list, max_length=3)


class AnswerRequest(BaseModel):
    request_id: str
    option_id: str = Field(max_length=64)


@router.post("/questions/next")
async def next_question(body: NextQuestionRequest, request: Request, caller: Caller = Depends(account_caller),
                        c: Container = Depends(get_container)) -> dict:
    if any(cat not in CATEGORY_IDS for cat in body.category_ids):
        raise ApiError(ErrorCode.INVALID_REQUEST, detail={"fields": ["category_ids"]})

    config = await c.config.get()
    if body.language not in set(config.features.competitive_languages) | set(config.features.ui_languages):
        raise ApiError(ErrorCode.FEATURE_DISABLED, detail={"feature": "question_language", "language": body.language})

    async def handler() -> dict:
        history = set(await c.exposure.history(caller.uid))
        difficulties = body.difficulties or list(Difficulty)
        candidates = []
        for difficulty in difficulties:
            for entry in await c.manifest_cache.get(body.language, "SURVIVAL", difficulty.value):
                if body.category_ids and entry.cat not in body.category_ids:
                    continue
                candidates.append(entry)
        if not candidates:
            raise ApiError(ErrorCode.NOT_FOUND, detail={"reason": "no_questions"})
        rng = random.Random(body.request_id)
        fresh = [e for e in candidates if e.qid not in history]
        pool = fresh or candidates
        rng.shuffle(pool)
        entry = bundle = image = None
        for candidate in pool[:MAX_ATTEMPTS]:
            loaded = (await c.question_repo.load_bundles([(candidate.gid, candidate.v)], body.language))[0]
            if bundle_problems(loaded, c.clock.now_ms(), "SURVIVAL") or not loaded.group.get("synova_enabled", True):
                continue
            image = None
            if candidate.m:
                # An image question is only served with its image (spec §9.1): sign it or pick another item.
                try:
                    expires = c.clock.now_ms() + MEDIA_TTL_MS
                    image = {"signed_image_url": await c.media_signer.sign(loaded.media["storage_path"], expires),
                             "image_expires_at_ms": expires,
                             "image_aspect": round(loaded.media["width"] / loaded.media["height"], 3),
                             "alt_text": (loaded.media.get("alt_text") or {}).get(body.language)}
                except Exception:  # noqa: BLE001 - signing failure: fall through to a text-only item
                    continue
            entry, bundle = candidate, loaded
            break
        if entry is None:
            raise ApiError(ErrorCode.CONFLICT, retryable=True, detail={"reason": "no_servable_question"})
        options = list(bundle.translation["options"])
        rng.shuffle(options)
        item_id = new_uuid()
        now = c.clock.now_ms()
        await c.store.set(f"synova_items/{item_id}", {
            "schema_version": 1, "uid": caller.uid, "gid": entry.gid, "v": entry.v, "qid": entry.qid,
            "language": body.language, "correct": bundle.private["correct_concept_id"],
            "served_at_ms": now, "answered": False,
        })
        await c.exposure.append(caller.uid, [entry.qid])
        await c.question_stats.apply([StatIntent(entry.gid, entry.v, body.language, "SYNOVA", {"shown": 1})])
        return {
            "schema_version": 1,
            "item_id": item_id,
            "question": {
                "qid": entry.qid, "category_id": entry.cat, "difficulty": entry.d,
                "text": bundle.translation["question_text"],
                "options": [{"option_id": o["concept_id"], "text": o["text"]} for o in options],
                **(image or {}),
            },
        }

    return await run_mutation(c, request, caller, "synova.next", body.model_dump(mode="json"), handler)


@router.post("/questions/{item_id}/answer")
async def answer(item_id: str, body: AnswerRequest, request: Request, caller: Caller = Depends(account_caller),
                 c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        path = f"synova_items/{item_id}"
        now = c.clock.now_ms()

        def txn_fn(txn) -> dict:
            item = txn.get(path)
            if not item or item["uid"] != caller.uid:
                raise ApiError(ErrorCode.NOT_FOUND)
            if item["answered"]:
                raise ApiError(ErrorCode.ANSWER_ALREADY_SUBMITTED)
            translation = txn.get(f"question_translations/{item['gid']}_{item['language']}_{item['v']}")
            if body.option_id not in {o["concept_id"] for o in (translation or {}).get("options", [])}:
                raise ApiError(ErrorCode.INVALID_OPTION)
            correct = body.option_id == item["correct"]
            txn.update(path, {"answered": True, "answer": body.option_id, "correct_answer": correct,
                              "answered_at_ms": now})
            return {**item, "is_correct": correct}

        item = await c.store.run_transaction(txn_fn)
        counts = {"attempted": 1, "correct" if item["is_correct"] else "wrong": 1,
                  "sum_response_ms": max(0, now - item["served_at_ms"])}
        await c.question_stats.apply([StatIntent(item["gid"], item["v"], item["language"], "SYNOVA", counts)])
        return {"schema_version": 1, "correct": item["is_correct"], "correct_option_id": item["correct"]}

    return await run_mutation(c, request, caller, f"synova.answer.{item_id}", body.model_dump(mode="json"), handler)
