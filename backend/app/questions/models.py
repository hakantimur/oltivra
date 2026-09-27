"""Shared question platform documents (spec §10, §18.3–18.5) and competitive validation (§9)."""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.common.ids import sha256_hex
from app.questions.taxonomy import is_valid_subcategory

QUESTION_PREFERRED_MAX = 120
QUESTION_HARD_MAX = 160
ANSWER_PREFERRED_MAX = 32
ANSWER_HARD_MAX = 48
COMPETITIVE_RELEVANCE_MIN = 4
CONCEPT_ID_RE = re.compile(r"^[a-z0-9_]{1,64}$")
LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")

_FORBIDDEN_OPTION_PATTERNS = (
    re.compile(r"\ball of the above\b", re.I),
    re.compile(r"\bnone of the above\b", re.I),
    re.compile(r"\bhepsi\b|\bhiçbiri\b|\byukarıdakilerin\b", re.I),
)


class Difficulty(StrEnum):
    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"

    def one_band_lower(self) -> Difficulty:
        """Rescue-round difficulty: one band lower, never below Easy (spec §4.3)."""
        return {Difficulty.HARD: Difficulty.MEDIUM}.get(self, Difficulty.EASY)


class QuestionStatus(StrEnum):
    DRAFT = "DRAFT"
    GENERATED = "GENERATED"
    VALIDATION_PENDING = "VALIDATION_PENDING"
    VERIFIED = "VERIFIED"
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"


ALLOWED_TRANSITIONS: dict[QuestionStatus, set[QuestionStatus]] = {
    QuestionStatus.DRAFT: {QuestionStatus.GENERATED, QuestionStatus.VALIDATION_PENDING, QuestionStatus.RETIRED},
    QuestionStatus.GENERATED: {QuestionStatus.VALIDATION_PENDING, QuestionStatus.DRAFT, QuestionStatus.RETIRED},
    QuestionStatus.VALIDATION_PENDING: {QuestionStatus.VERIFIED, QuestionStatus.DRAFT, QuestionStatus.RETIRED},
    QuestionStatus.VERIFIED: {QuestionStatus.ACTIVE, QuestionStatus.RETIRED, QuestionStatus.QUARANTINED},
    QuestionStatus.ACTIVE: {QuestionStatus.QUARANTINED, QuestionStatus.RETIRED},
    QuestionStatus.QUARANTINED: {QuestionStatus.VALIDATION_PENDING, QuestionStatus.ACTIVE, QuestionStatus.RETIRED},
    QuestionStatus.RETIRED: {QuestionStatus.VALIDATION_PENDING},
}

COMPETITIVE_MODES = ("QUICK", "SURVIVAL")


class OptionText(BaseModel):
    concept_id: str
    text: str

    @field_validator("concept_id")
    @classmethod
    def _concept(cls, value: str) -> str:
        if not CONCEPT_ID_RE.match(value):
            raise ValueError("concept_id must be lowercase snake_case")
        return value


class QuestionGroup(BaseModel):
    schema_version: int = 1
    id: str
    qid: int
    category_id: str
    subcategory_id: str
    declared_difficulty: Difficulty
    global_relevance_score: int = Field(ge=1, le=5)
    media_asset_id: str | None = None
    time_sensitive: bool = False
    review_after_ms: int | None = None
    status: QuestionStatus = QuestionStatus.DRAFT
    verified: bool = False
    competitive_enabled: bool = False
    synova_enabled: bool = True
    version: int = 1
    canonical_language: str = "en"
    concept_hash: str = ""
    modes: list[str] = Field(default_factory=lambda: list(COMPETITIVE_MODES))
    created_at_ms: int = 0
    updated_at_ms: int = 0

    @field_validator("subcategory_id")
    @classmethod
    def _sub(cls, value: str, info) -> str:
        category = info.data.get("category_id")
        if category and not is_valid_subcategory(category, value):
            raise ValueError(f"unknown subcategory {value} for {category}")
        return value


class QuestionTranslation(BaseModel):
    schema_version: int = 1
    question_group_id: str
    question_version: int
    language: str
    question_text: str
    options: list[OptionText]
    translation_verified: bool = False
    competitive_text_valid: bool = False
    text_hash: str = ""

    @field_validator("language")
    @classmethod
    def _lang(cls, value: str) -> str:
        if not LANGUAGE_RE.match(value):
            raise ValueError("language must be a BCP-47 tag")
        return value


class PrivateAnswer(BaseModel):
    schema_version: int = 1
    question_group_id: str
    question_version: int
    correct_concept_id: str
    source_refs: list[str] = Field(default_factory=list)
    verified_by: str | None = None
    verified_at_ms: int | None = None


class MediaAsset(BaseModel):
    schema_version: int = 1
    id: str
    storage_path: str
    content_type: str = "image/webp"
    width: int
    height: int
    bytes: int
    alt_text: dict[str, str] = Field(default_factory=dict)
    source: str
    author: str | None = None
    license: str
    attribution: str | None = None
    copyright_status: str
    review_status: str = "PENDING"
    question_group_id: str | None = None
    question_version: int | None = None
    # Spec §9.1 preferred targets (<=200 KB, <=1024 px); exceeding them is a warning, not a hard failure.
    preferred_limits_ok: bool = True
    created_at_ms: int | None = None

    @property
    def aspect_ratio(self) -> float:
        return round(self.width / self.height, 4) if self.height else 1.0

    @property
    def delivery_valid(self) -> bool:
        return (self.content_type == "image/webp" and self.review_status == "APPROVED"
                and self.bytes <= 400_000 and max(self.width, self.height) <= 2048)


MEDIA_PREFERRED_MAX_BYTES = 200_000
MEDIA_PREFERRED_MAX_DIMENSION = 1024
# Versioned question media never changes in place (spec §34.1), so caches may keep it forever.
IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"
MEDIA_EDITABLE_STATUSES = {"DRAFT", "GENERATED", "VALIDATION_PENDING"}


def question_media_path(group_id: str, version: int) -> str:
    return f"questions/{group_id}/v{version}/main.webp"


def is_webp(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def media_warnings(size: int, width: int, height: int) -> list[str]:
    warnings = []
    if size > MEDIA_PREFERRED_MAX_BYTES:
        warnings.append("above_preferred_bytes")
    if max(width, height) > MEDIA_PREFERRED_MAX_DIMENSION:
        warnings.append("above_preferred_dimension")
    return warnings


def translation_doc_id(group_id: str, language: str, version: int) -> str:
    return f"{group_id}_{language}_{version}"


def private_doc_id(group_id: str, version: int) -> str:
    return f"{group_id}_{version}"


def normalise_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"[^\w\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def text_hash(question_text: str, options: list[OptionText]) -> str:
    parts = [normalise_text(question_text), *sorted(normalise_text(o.text) for o in options)]
    return sha256_hex("|".join(parts))


def concept_hash(canonical_question: str, correct_concept_id: str) -> str:
    return sha256_hex(f"{normalise_text(canonical_question)}|{correct_concept_id}")


def validate_competitive_text(translation: QuestionTranslation, correct_concept_id: str | None = None) -> list[str]:
    """Return a list of violations; empty means the text is competitive-valid (spec §9)."""
    problems: list[str] = []
    q = translation.question_text.strip()
    if not q:
        problems.append("question_empty")
    if len(q) > QUESTION_HARD_MAX:
        problems.append("question_too_long")
    if len(translation.options) != 4:
        problems.append("options_not_four")
    concept_ids = [o.concept_id for o in translation.options]
    if len(set(concept_ids)) != len(concept_ids):
        problems.append("duplicate_concepts")
    texts = [normalise_text(o.text) for o in translation.options]
    if len(set(texts)) != len(texts):
        problems.append("duplicate_option_text")
    for option in translation.options:
        if not option.text.strip():
            problems.append("option_empty")
        if len(option.text) > ANSWER_HARD_MAX:
            problems.append("option_too_long")
        if any(p.search(option.text) for p in _FORBIDDEN_OPTION_PATTERNS):
            problems.append("forbidden_option_pattern")
    if correct_concept_id is not None and correct_concept_id not in concept_ids:
        problems.append("correct_not_in_options")
    return sorted(set(problems))


def competitive_eligibility(
    group: dict[str, Any],
    translation: dict[str, Any] | None,
    now_ms: int,
    media: dict[str, Any] | None = None,
    mode: str | None = None,
) -> list[str]:
    """Reasons a question version cannot enter competitive selection (spec §9.3, §26.3). Empty = eligible."""
    reasons: list[str] = []
    if group.get("status") != QuestionStatus.ACTIVE:
        reasons.append("not_active")
    if not group.get("verified"):
        reasons.append("not_verified")
    if not group.get("competitive_enabled"):
        reasons.append("competitive_disabled")
    if group.get("global_relevance_score", 0) < COMPETITIVE_RELEVANCE_MIN:
        reasons.append("low_global_relevance")
    review_after = group.get("review_after_ms")
    if review_after is not None and review_after <= now_ms:
        reasons.append("review_expired")
    if mode and mode not in group.get("modes", COMPETITIVE_MODES):
        reasons.append("mode_not_eligible")
    if translation is None:
        reasons.append("translation_missing")
    else:
        if not translation.get("translation_verified"):
            reasons.append("translation_unverified")
        if not translation.get("competitive_text_valid"):
            reasons.append("text_invalid")
        if translation.get("question_version") != group.get("version"):
            reasons.append("translation_version_mismatch")
    if group.get("media_asset_id"):
        if media is None:
            reasons.append("media_missing")
        elif not MediaAsset.model_validate(media).delivery_valid:
            reasons.append("media_invalid")
    return reasons
