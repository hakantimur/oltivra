"""AI batch question generation (spec §11.1).

AI content starts in GENERATED and never enters the competitive pool automatically: every accepted candidate
still needs human review (sources included) before VERIFIED -> ACTIVE. Pipeline:

    versioned prompt -> candidate generation -> normalisation -> exact duplicate check -> semantic duplicate check
    -> answer validation -> global relevance validation -> translation check -> length validation
    -> source/provenance collection -> GENERATED (awaiting human review)

Provider/model/prompt version are stored on every job and question for audit.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

import httpx

from app.admin.duplicates import cosine, embed
from app.common.errors import ApiError, ErrorCode
from app.common.ids import new_uuid
from app.common.tasks import TaskKind, TaskRequest
from app.questions.models import (
    ANSWER_HARD_MAX,
    QUESTION_HARD_MAX,
    OptionText,
    QuestionStatus,
    QuestionTranslation,
    text_hash,
    validate_competitive_text,
)
from app.questions.repository import TranslationInput
from app.questions.taxonomy import is_valid_subcategory

log = logging.getLogger("oltivra.ai_generation")

PROMPT_VERSION = "qgen-v1"
PROMPTS = {
    "qgen-v1": (
        "You write multiple-choice trivia questions for a real-time global quiz game. Rules:\n"
        "- Exactly four options; exactly one is correct; no 'all/none of the above'.\n"
        f"- Question at most {QUESTION_HARD_MAX} characters, each option at most {ANSWER_HARD_MAX} characters, in "
        "every language.\n"
        "- Facts must be globally known and stable (not region-specific, not time-sensitive), unambiguous and "
        "verifiable. Rate global relevance from 1 (local/niche) to 5 (known worldwide).\n"
        "- Give each option a stable lowercase concept_id (a-z, 0-9, _) shared across languages.\n"
        "- Translations must be natural, not literal, and keep the same meaning and correct option.\n"
        "- Cite at least one reputable source URL per question. Sources will be checked by a human.\n"
        "- Do not repeat facts across the batch."
    ),
}
STALE_RUNNING_MS = 10 * 60_000
MAX_ATTEMPTS = 3


@dataclass
class GenerationSpec:
    category_id: str
    subcategory_id: str
    difficulty: str
    canonical_language: str
    required_languages: list[str]
    count: int
    min_global_relevance: int
    media_required: bool = False

    @property
    def languages(self) -> list[str]:
        return sorted({self.canonical_language, *self.required_languages})


@dataclass
class GeneratedBatch:
    provider: str
    model: str
    candidates: list[dict[str, Any]] = field(default_factory=list)


class QuestionGenerator(Protocol):
    provider: str
    model: str

    async def generate(self, spec: GenerationSpec, prompt_version: str) -> GeneratedBatch: ...


# ---------------------------------------------------------------------------------------------- providers


def _tool_schema(languages: list[str]) -> dict[str, Any]:
    text = {"type": "object", "properties": {lang: {"type": "string"} for lang in languages},
            "required": languages}
    return {
        "type": "object",
        "properties": {"questions": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "question": text,
                "options": {"type": "array", "minItems": 4, "maxItems": 4, "items": {
                    "type": "object", "properties": {"concept_id": {"type": "string"}, "text": text},
                    "required": ["concept_id", "text"]}},
                "correct_concept_id": {"type": "string"},
                "global_relevance_score": {"type": "integer", "minimum": 1, "maximum": 5},
                "sources": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["question", "options", "correct_concept_id", "global_relevance_score", "sources"],
        }}},
        "required": ["questions"],
    }


class AnthropicQuestionGenerator:
    """Claude Messages API with a forced tool call for structured output."""

    provider = "anthropic"
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str, model: str, client: httpx.AsyncClient | None = None) -> None:
        if not api_key:
            raise ValueError("anthropic_api_key is required for the anthropic generator")
        self._key = api_key
        self.model = model
        self._client = client

    async def generate(self, spec: GenerationSpec, prompt_version: str) -> GeneratedBatch:
        user = (f"Write {spec.count} {spec.difficulty} questions. Main category: {spec.category_id}; "
                f"subcategory: {spec.subcategory_id}. Canonical language: {spec.canonical_language}. "
                f"Provide text in: {', '.join(spec.languages)}. Minimum global relevance: "
                f"{spec.min_global_relevance}." + (" Each question must be answerable from an accompanying image; "
                                                   "describe the needed image in the sources list as 'image: ...'."
                                                   if spec.media_required else ""))
        body = {"model": self.model, "max_tokens": 8000, "system": PROMPTS[prompt_version],
                "messages": [{"role": "user", "content": user}],
                "tools": [{"name": "submit_questions", "description": "Submit the generated questions.",
                           "input_schema": _tool_schema(spec.languages)}],
                "tool_choice": {"type": "tool", "name": "submit_questions"}}
        headers = {"x-api-key": self._key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        client = self._client or httpx.AsyncClient(timeout=120)
        try:
            res = await client.post(self.URL, json=body, headers=headers)
        finally:
            if self._client is None:
                await client.aclose()
        if res.status_code != 200:
            raise RuntimeError(f"anthropic_http_{res.status_code}")
        blocks = res.json().get("content") or []
        tool = next((b for b in blocks if b.get("type") == "tool_use" and b.get("name") == "submit_questions"), None)
        if not tool:
            raise RuntimeError("anthropic_no_tool_output")
        return GeneratedBatch(self.provider, self.model, list((tool.get("input") or {}).get("questions") or []))


def _q(en: str, tr: str) -> dict[str, str]:
    return {"en": en, "tr": tr}


def _opts(*pairs: tuple[str, str, str]) -> list[dict[str, Any]]:
    return [{"concept_id": cid, "text": _q(en, tr)} for cid, en, tr in pairs]


# Scripted output for local/emulator development and tests; includes deliberate pipeline rejects.
FAKE_CANDIDATES: list[dict[str, Any]] = [
    {"question": _q("Which composer wrote the opera The Magic Flute?", "Sihirli Flüt operasını hangi besteci yazdı?"),
     "options": _opts(("mozart", "Mozart", "Mozart"), ("beethoven", "Beethoven", "Beethoven"),
                      ("verdi", "Verdi", "Verdi"), ("wagner", "Wagner", "Wagner")),
     "correct_concept_id": "mozart", "global_relevance_score": 5,
     "sources": ["https://www.britannica.com/topic/The-Magic-Flute"]},
    {"question": _q("In which city is the Sagrada Familia basilica located?",
                    "Sagrada Familia bazilikası hangi şehirdedir?"),
     "options": _opts(("barcelona", "Barcelona", "Barselona"), ("madrid", "Madrid", "Madrid"),
                      ("seville", "Seville", "Sevilla"), ("valencia", "Valencia", "Valensiya")),
     "correct_concept_id": "barcelona", "global_relevance_score": 5,
     "sources": ["https://sagradafamilia.org/"]},
    {"question": _q("In which city is the Sagrada Familia basilica situated?",
                    "Sagrada Familia bazilikası hangi şehirde bulunur?"),
     "options": _opts(("barcelona", "Barcelona", "Barselona"), ("lisbon", "Lisbon", "Lizbon"),
                      ("rome", "Rome", "Roma"), ("paris", "Paris", "Paris")),
     "correct_concept_id": "barcelona", "global_relevance_score": 5, "sources": ["https://sagradafamilia.org/"]},
    {"question": _q("Which village hosts the annual Lower Wobbleton turnip fair?",
                    "Yıllık Lower Wobbleton şalgam fuarı hangi köyde yapılır?"),
     "options": _opts(("a", "Upper Wobbleton", "Upper Wobbleton"), ("b", "Lower Wobbleton", "Lower Wobbleton"),
                      ("c", "Middle Wobbleton", "Middle Wobbleton"), ("d", "Wobbleton Cross", "Wobbleton Cross")),
     "correct_concept_id": "b", "global_relevance_score": 1, "sources": ["https://example.org/turnips"]},
    {"question": _q("Which instrument has 88 keys in its standard modern form?",
                    "Standart modern hâliyle 88 tuşu olan çalgı hangisidir?"),
     "options": _opts(("piano", "Piano", "Piyano"), ("organ", "Organ", "Org"), ("harp", "Harp", "Arp"),
                      ("accordion", "Accordion", "Akordeon")),
     "correct_concept_id": "harpsichord", "global_relevance_score": 5, "sources": ["https://www.britannica.com/"]},
    {"question": {"en": "Which programming language was created by Guido van Rossum?"},
     "options": [{"concept_id": c, "text": {"en": t}} for c, t in (("python", "Python"), ("ruby", "Ruby"),
                                                                    ("perl", "Perl"), ("java", "Java"))],
     "correct_concept_id": "python", "global_relevance_score": 4, "sources": ["https://www.python.org/"]},
    {"question": _q("What colour are the stars on the flag of the European Union?",
                    "Avrupa Birliği bayrağındaki yıldızlar ne renktir?"),
     "options": _opts(("gold", "Gold", "Altın sarısı"), ("white", "White", "Beyaz"), ("blue", "Blue", "Mavi"),
                      ("silver", "Silver stars outlined with a thin dark blue border line",
                       "İnce lacivert bir kenar çizgisiyle çevrelenmiş gümüş yıldızlar")),
     "correct_concept_id": "gold", "global_relevance_score": 4, "sources": ["https://european-union.europa.eu/"]},
    {"question": _q("Which country gifted the Statue of Liberty to the United States?",
                    "Özgürlük Heykeli'ni ABD'ye hangi ülke hediye etti?"),
     "options": _opts(("france", "France", "Fransa"), ("uk", "United Kingdom", "Birleşik Krallık"),
                      ("spain", "Spain", "İspanya"), ("italy", "Italy", "İtalya")),
     "correct_concept_id": "france", "global_relevance_score": 5, "sources": []},
]


class FakeQuestionGenerator:
    provider = "fake"
    model = "scripted-v1"

    def __init__(self, candidates: list[dict[str, Any]] | None = None) -> None:
        self._candidates = candidates if candidates is not None else FAKE_CANDIDATES

    async def generate(self, spec: GenerationSpec, prompt_version: str) -> GeneratedBatch:
        return GeneratedBatch(self.provider, self.model, [dict(c) for c in self._candidates[:spec.count]])


# ---------------------------------------------------------------------------------------------- pipeline


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(value or ""))).strip()


def _concept(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", _clean(value).lower()).strip("_")[:64]


def normalise_candidate(raw: dict[str, Any]) -> dict[str, Any]:
    question = {lang: _clean(text) for lang, text in (raw.get("question") or {}).items() if _clean(text)}
    options = []
    for option in raw.get("options") or []:
        texts = option.get("text") or {}
        options.append({"concept_id": _concept(option.get("concept_id")),
                        "text": {lang: _clean(t) for lang, t in texts.items() if _clean(t)}})
    sources = [_clean(s) for s in raw.get("sources") or [] if _clean(s)][:10]
    try:
        relevance = int(raw.get("global_relevance_score") or 0)
    except (TypeError, ValueError):
        relevance = 0
    return {"question": question, "options": options, "correct_concept_id": _concept(raw.get("correct_concept_id")),
            "global_relevance_score": relevance, "sources": sources}


def _translation(candidate: dict[str, Any], language: str) -> QuestionTranslation:
    return QuestionTranslation(
        question_group_id="candidate", question_version=1, language=language,
        question_text=candidate["question"].get(language, ""),
        options=[OptionText(concept_id=o["concept_id"], text=o["text"].get(language, ""))
                 for o in candidate["options"]])


def answer_problems(candidate: dict[str, Any]) -> list[str]:
    options = candidate["options"]
    concepts = [o["concept_id"] for o in options]
    problems = []
    if len(options) != 4:
        problems.append("options_not_four")
    if len(set(concepts)) != len(concepts) or not all(concepts):
        problems.append("invalid_concepts")
    if candidate["correct_concept_id"] not in concepts:
        problems.append("correct_not_in_options")
    return problems


def job_path(job_id: str) -> str:
    return f"ai_generation_jobs/{job_id}"


class GenerationService:
    def __init__(self, container, generator: QuestionGenerator) -> None:
        self._c = container
        self.generator = generator

    async def create_job(self, actor: str, spec: GenerationSpec) -> dict[str, Any]:
        c = self._c
        config = await c.config.get()
        if not is_valid_subcategory(spec.category_id, spec.subcategory_id):
            raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "unknown_subcategory"})
        if spec.count > config.content.ai_max_candidates_per_job:
            raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "too_many_candidates",
                                                              "max": config.content.ai_max_candidates_per_job})
        spec.min_global_relevance = max(spec.min_global_relevance, config.content.ai_min_global_relevance)
        now = c.clock.now_ms()
        job = {"schema_version": 1, "job_id": new_uuid(), "status": "QUEUED", "spec": asdict(spec),
               "created_by": actor, "created_at_ms": now, "updated_at_ms": now, "attempts": 0,
               "provider": self.generator.provider, "model": self.generator.model, "prompt_version": PROMPT_VERSION,
               "accepted": [], "rejected": []}
        await c.store.create(job_path(job["job_id"]), job)
        await self._schedule(job["job_id"], 0)
        await c.audit.record(actor=actor, action="AI_JOB_CREATE", subject=f"ai_job:{job['job_id']}",
                             detail={"category_id": spec.category_id, "count": spec.count})
        return job

    async def _schedule(self, job_id: str, attempt: int) -> None:
        c = self._c
        await c.tasks.schedule(TaskRequest(TaskKind.QUESTION_BATCH, c.settings.shard_ids[0], c.clock.now_ms(),
                                           {"job_id": job_id}, (job_id, str(attempt))))

    async def retry(self, job_id: str, actor: str) -> dict[str, Any]:
        c = self._c
        job = await c.store.get(job_path(job_id))
        if not job:
            raise ApiError(ErrorCode.NOT_FOUND)
        if job["status"] != "FAILED":
            raise ApiError(ErrorCode.CONFLICT, detail={"reason": "only_failed_jobs_retry"})
        await c.store.update(job_path(job_id), {"status": "QUEUED", "updated_at_ms": c.clock.now_ms()})
        await self._schedule(job_id, int(job.get("attempts", 0)))
        await c.audit.record(actor=actor, action="AI_JOB_RETRY", subject=f"ai_job:{job_id}")
        return {**job, "status": "QUEUED"}

    async def _claim(self, job_id: str) -> dict[str, Any] | None:
        c = self._c
        now = c.clock.now_ms()

        def txn_fn(txn) -> dict[str, Any] | None:
            job = txn.get(job_path(job_id))
            if not job or job["status"] in ("COMPLETED", "FAILED"):
                return None
            if job["status"] == "RUNNING" and now - int(job.get("started_at_ms", 0)) < STALE_RUNNING_MS:
                return None  # a duplicate task while another worker is running: no-op
            claimed = {**job, "status": "RUNNING", "started_at_ms": now, "updated_at_ms": now,
                       "attempts": int(job.get("attempts", 0)) + 1}
            txn.set(job_path(job_id), claimed)
            return claimed

        return await c.store.run_transaction(txn_fn)

    async def run(self, job_id: str) -> dict[str, Any]:
        c = self._c
        job = await self._claim(job_id)
        if job is None:
            return {"changed": False}
        spec = GenerationSpec(**job["spec"])
        try:
            batch = await self.generator.generate(spec, job["prompt_version"])
        except Exception as exc:  # noqa: BLE001 - provider failures are recorded, retried by an admin
            status = "FAILED" if job["attempts"] >= MAX_ATTEMPTS else "QUEUED"
            await c.store.update(job_path(job_id), {"status": status, "error": type(exc).__name__ + ": " +
                                                    str(exc)[:200], "updated_at_ms": c.clock.now_ms()})
            log.warning("ai_job_failed", extra={"job_id": job_id, "attempt": job["attempts"]})
            if status == "QUEUED":
                raise  # let the task queue retry with backoff
            return {"changed": True, "status": status}
        accepted, rejected = await self._pipeline(job, spec, batch)
        await c.store.update(job_path(job_id), {
            "status": "COMPLETED", "accepted": accepted, "rejected": rejected, "provider": batch.provider,
            "model": batch.model, "completed_at_ms": c.clock.now_ms(), "updated_at_ms": c.clock.now_ms(),
            "error": None})
        if accepted:
            c.duplicates.invalidate()
        return {"changed": True, "status": "COMPLETED", "accepted": len(accepted), "rejected": len(rejected)}

    async def _pipeline(self, job: dict[str, Any], spec: GenerationSpec, batch: GeneratedBatch
                        ) -> tuple[list[str], list[dict[str, Any]]]:
        c = self._c
        canonical = spec.canonical_language
        accepted: list[str] = []
        rejected: list[dict[str, Any]] = []
        seen_hashes: set[str] = set()
        seen_vectors: list[dict[int, float]] = []
        threshold = (await c.config.get()).content.near_duplicate_threshold
        for index, raw in enumerate(batch.candidates[:spec.count]):
            candidate = normalise_candidate(raw)
            text = candidate["question"].get(canonical, "")
            reasons: list[str] = []
            details: dict[str, Any] = {}
            canonical_tr = _translation(candidate, canonical)
            exact = text_hash(text, canonical_tr.options)
            if not text:
                reasons.append(f"translation_missing_{canonical}")
            # 1) Exact duplicate (existing pool and within this batch).
            if text and (exact in seen_hashes or await c.store.query(_hash_query(exact))):
                reasons.append("exact_duplicate")
            # 2) Semantic duplicate.
            if text and not reasons:
                vector = embed(text)
                if any(cosine(vector, v) >= threshold for v in seen_vectors):
                    reasons.append("semantic_duplicate_in_batch")
                else:
                    found = await c.duplicates.candidates(question_text=text, language=canonical)
                    if found["is_duplicate"]:
                        reasons.append("semantic_duplicate")
                        details["duplicates"] = [d["question_group_id"] for d in found["duplicates"][:3]]
            # 3) Answer validation.
            reasons += answer_problems(candidate)
            # 4) Global relevance.
            if candidate["global_relevance_score"] < spec.min_global_relevance:
                reasons.append("low_global_relevance")
            # 5) Required translations.
            for language in spec.languages:
                if language not in candidate["question"] or any(language not in o["text"]
                                                                  for o in candidate["options"]):
                    reasons.append(f"translation_missing_{language}")
            # 6) Length / text rules per language.
            for language in spec.languages:
                if language in candidate["question"]:
                    for problem in validate_competitive_text(_translation(candidate, language)):
                        if problem in ("question_too_long", "option_too_long", "option_empty",
                                       "duplicate_option_text", "forbidden_option_pattern"):
                            reasons.append(f"{problem}_{language}")
            # 7) Provenance: at least one cited source (still unverified until human review).
            if not candidate["sources"]:
                reasons.append("no_source")
            if reasons:
                rejected.append({"index": index, "text": text[:QUESTION_HARD_MAX], "reasons": sorted(set(reasons)),
                                 **details})
                continue
            seen_hashes.add(exact)
            seen_vectors.append(embed(text))
            group = await c.question_repo.create_question(
                category_id=spec.category_id, subcategory_id=spec.subcategory_id, difficulty=spec.difficulty,
                global_relevance_score=candidate["global_relevance_score"], canonical_language=canonical,
                translations=[TranslationInput(lang, candidate["question"][lang],
                                               [OptionText(concept_id=o["concept_id"], text=o["text"][lang])
                                                for o in candidate["options"]], False) for lang in spec.languages],
                correct_concept_id=candidate["correct_concept_id"], source_refs=candidate["sources"],
                actor_uid=job["created_by"], status=QuestionStatus.GENERATED,
                extra={"created_by": job["created_by"], "media_required": spec.media_required,
                       "ai": {"provider": batch.provider, "model": batch.model,
                              "prompt_version": job["prompt_version"], "job_id": job["job_id"],
                              "candidate_index": index, "sources_unverified": True}})
            accepted.append(group["id"])
        return accepted, rejected


def _hash_query(exact: str):
    from app.common.store.docstore import Query

    return Query("question_translations").filter("text_hash", "==", exact).take(1)
