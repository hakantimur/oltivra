"""Question platform persistence: groups, immutable versions, translations, private answers, media."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.common.clock import Clock
from app.common.errors import ApiError, ErrorCode
from app.common.ids import new_uuid
from app.common.store.docstore import DocStore
from app.questions.models import (
    ALLOWED_TRANSITIONS,
    MediaAsset,
    OptionText,
    PrivateAnswer,
    QuestionGroup,
    QuestionStatus,
    QuestionTranslation,
    concept_hash,
    private_doc_id,
    text_hash,
    translation_doc_id,
    validate_competitive_text,
)

QID_COUNTER = "counters/question_qid"


@dataclass(frozen=True)
class QuestionBundle:
    group: dict[str, Any]
    translation: dict[str, Any] | None
    private: dict[str, Any] | None
    media: dict[str, Any] | None


@dataclass(frozen=True)
class TranslationInput:
    language: str
    question_text: str
    options: list[OptionText]
    verified: bool


class QuestionRepository:
    def __init__(self, store: DocStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    async def allocate_qids(self, count: int) -> list[int]:
        def txn_fn(txn) -> list[int]:
            doc = txn.get(QID_COUNTER)
            start = (doc or {}).get("next", 1)
            txn.set(QID_COUNTER, {"next": start + count})
            return list(range(start, start + count))

        return await self._store.run_transaction(txn_fn)

    async def get_group(self, group_id: str) -> dict[str, Any] | None:
        return await self._store.get(f"question_groups/{group_id}")

    async def load_bundles(self, refs: list[tuple[str, int]], language: str) -> list[QuestionBundle]:
        """Load (group, translation, private answer, media) for (group_id, version) refs — server only."""
        if not refs:
            return []
        groups = await self._store.get_many([f"question_groups/{gid}" for gid, _ in refs])
        translations = await self._store.get_many(
            [f"question_translations/{translation_doc_id(gid, language, v)}" for gid, v in refs])
        privates = await self._store.get_many([f"question_private/{private_doc_id(gid, v)}" for gid, v in refs])
        media_ids = [(g or {}).get("media_asset_id") for g in groups]
        media_docs = await self._store.get_many([f"media_assets/{m}" for m in media_ids if m])
        media_iter = iter(media_docs)
        bundles = []
        for group, translation, private, media_id in zip(groups, translations, privates, media_ids, strict=True):
            media = next(media_iter) if media_id else None
            bundles.append(QuestionBundle(group or {}, translation, private, media))
        return bundles

    async def create_question(
        self,
        *,
        category_id: str,
        subcategory_id: str,
        difficulty: str,
        global_relevance_score: int,
        canonical_language: str,
        translations: list[TranslationInput],
        correct_concept_id: str,
        source_refs: list[str],
        actor_uid: str,
        status: QuestionStatus = QuestionStatus.DRAFT,
        time_sensitive: bool = False,
        review_after_ms: int | None = None,
        media_asset_id: str | None = None,
        group_id: str | None = None,
        qid: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = self._clock.now_ms()
        group_id = group_id or new_uuid()
        qid = qid if qid is not None else (await self.allocate_qids(1))[0]
        canonical = next((t for t in translations if t.language == canonical_language), None)
        if canonical is None:
            raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "canonical_translation_missing"})
        verified = status in (QuestionStatus.VERIFIED, QuestionStatus.ACTIVE)
        group = QuestionGroup(
            id=group_id, qid=qid, category_id=category_id, subcategory_id=subcategory_id,
            declared_difficulty=difficulty, global_relevance_score=global_relevance_score,
            media_asset_id=media_asset_id, time_sensitive=time_sensitive, review_after_ms=review_after_ms,
            status=status, verified=verified, competitive_enabled=verified and global_relevance_score >= 4,
            version=1, canonical_language=canonical_language,
            concept_hash=concept_hash(canonical.question_text, correct_concept_id),
            created_at_ms=now, updated_at_ms=now,
        )
        await self._write_version(group, translations, correct_concept_id, source_refs, actor_uid if verified else None,
                                  extra)
        return group.model_dump()

    async def _write_version(self, group: QuestionGroup, translations: list[TranslationInput], correct: str,
                             source_refs: list[str], verified_by: str | None, extra: dict[str, Any] | None) -> None:
        now = self._clock.now_ms()
        for t in translations:
            doc = QuestionTranslation(question_group_id=group.id, question_version=group.version,
                                      language=t.language, question_text=t.question_text, options=t.options,
                                      translation_verified=t.verified)
            problems = validate_competitive_text(doc, correct)
            doc.competitive_text_valid = not problems
            doc.text_hash = text_hash(t.question_text, t.options)
            await self._store.set(f"question_translations/{translation_doc_id(group.id, t.language, group.version)}",
                                  doc.model_dump())
        private = PrivateAnswer(question_group_id=group.id, question_version=group.version,
                                correct_concept_id=correct, source_refs=source_refs, verified_by=verified_by,
                                verified_at_ms=now if verified_by else None)
        await self._store.set(f"question_private/{private_doc_id(group.id, group.version)}", private.model_dump())
        data = group.model_dump()
        data["languages"] = sorted({t.language for t in translations})
        if extra:
            data.update(extra)
        await self._store.set(f"question_groups/{group.id}", data)
        await self._store.set(f"question_versions/{group.id}_{group.version}", {
            "schema_version": 1, "question_group_id": group.id, "version": group.version,
            "created_at_ms": now, "snapshot": data,
        })

    async def new_version(self, group_id: str, *, translations: list[TranslationInput], correct_concept_id: str,
                          source_refs: list[str], actor_uid: str, changes: dict[str, Any] | None = None
                          ) -> dict[str, Any]:
        """Editing creates a new immutable version; history is never rewritten (spec §0.2)."""
        current = await self.get_group(group_id)
        if not current:
            raise ApiError(ErrorCode.NOT_FOUND)
        merged = {**current, **(changes or {})}
        merged.update({
            "version": current["version"] + 1,
            "status": QuestionStatus.VALIDATION_PENDING.value,
            "verified": False,
            "competitive_enabled": False,
            "updated_at_ms": self._clock.now_ms(),
        })
        group = QuestionGroup.model_validate(merged)
        canonical = next((t for t in translations if t.language == group.canonical_language), translations[0])
        group.concept_hash = concept_hash(canonical.question_text, correct_concept_id)
        await self._write_version(group, translations, correct_concept_id, source_refs, None, None)
        return group.model_dump()

    async def transition(self, group_id: str, target: QuestionStatus, actor_uid: str, reason: str) -> dict[str, Any]:
        now = self._clock.now_ms()
        path = f"question_groups/{group_id}"

        def txn_fn(txn) -> dict[str, Any]:
            group = txn.get(path)
            if not group:
                raise ApiError(ErrorCode.NOT_FOUND)
            current = QuestionStatus(group["status"])
            if target != current and target not in ALLOWED_TRANSITIONS[current]:
                raise ApiError(ErrorCode.CONFLICT, detail={"from": current.value, "to": target.value})
            updates: dict[str, Any] = {"status": target.value, "updated_at_ms": now}
            if target == QuestionStatus.VERIFIED or (target == QuestionStatus.ACTIVE and group.get("verified")):
                updates["verified"] = True
                updates["competitive_enabled"] = group.get("global_relevance_score", 0) >= 4
            if target in (QuestionStatus.QUARANTINED, QuestionStatus.RETIRED, QuestionStatus.VALIDATION_PENDING):
                updates["competitive_enabled"] = False
            if target == QuestionStatus.VALIDATION_PENDING:
                updates["verified"] = False
            if target == QuestionStatus.ACTIVE and not (group.get("verified") or updates.get("verified")):
                raise ApiError(ErrorCode.CONFLICT, detail={"reason": "not_verified"})
            txn.update(path, updates)
            txn.set(f"question_status_history/{group_id}_{now}", {
                "schema_version": 1, "question_group_id": group_id, "from": current.value, "to": target.value,
                "actor_uid": actor_uid, "reason": reason, "at_ms": now,
            })
            return {**group, **updates}

        return await self._store.run_transaction(txn_fn)

    async def mark_translation_verified(self, group_id: str, version: int, language: str, verified: bool) -> None:
        await self._store.update(f"question_translations/{translation_doc_id(group_id, language, version)}",
                                 {"translation_verified": verified})

    async def put_media(self, asset: MediaAsset) -> None:
        await self._store.set(f"media_assets/{asset.id}", asset.model_dump())
