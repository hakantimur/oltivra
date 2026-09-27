"""Duplicate detection (spec §11.2): normalised exact-text hash, concept/fact hash, semantic similarity.

Semantic similarity uses a hashed character-trigram + word vector embedding computed locally (no external
provider is required); the index is cached per instance and refreshed periodically. A paraphrase of the same
fact above the versioned threshold is normally rejected rather than counted as a distinct question group.
"""

from __future__ import annotations

import hashlib
import math
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.common.store.docstore import Query
from app.questions.models import normalise_text

DIMENSIONS = 4096
INDEX_TTL_S = 300.0


def embed(text: str) -> dict[int, float]:
    """Sparse, L2-normalised vector of hashed character trigrams and words."""
    norm = normalise_text(text)
    features: Counter[str] = Counter()
    padded = f"  {norm}  "
    for i in range(len(padded) - 2):
        features["c:" + padded[i:i + 3]] += 1
    for word in norm.split():
        if len(word) > 2:
            features["w:" + word] += 2
    vector: dict[int, float] = {}
    for feature, weight in features.items():
        index = int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=4).digest(), "big") % DIMENSIONS
        vector[index] = vector.get(index, 0.0) + weight
    length = math.sqrt(sum(v * v for v in vector.values())) or 1.0
    return {k: v / length for k, v in vector.items()}


def cosine(a: dict[int, float], b: dict[int, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


@dataclass
class _Entry:
    gid: str
    version: int
    text: str
    vector: dict[int, float]


class DuplicateService:
    def __init__(self, container) -> None:
        self._c = container
        self._index: dict[str, tuple[float, list[_Entry]]] = {}

    async def _entries(self, language: str) -> list[_Entry]:
        cached = self._index.get(language)
        if cached and time.monotonic() - cached[0] < INDEX_TTL_S:
            return cached[1]
        groups = {r.id: r.data for r in await self._c.store.query(Query("question_groups"))}
        entries = []
        paths = [f"question_translations/{gid}_{language}_{g['version']}" for gid, g in groups.items()]
        docs = await self._c.store.get_many(paths) if paths else []
        for (gid, group), doc in zip(groups.items(), docs, strict=True):
            if doc and group.get("status") != "RETIRED":
                entries.append(_Entry(gid, group["version"], doc["question_text"], embed(doc["question_text"])))
        self._index[language] = (time.monotonic(), entries)
        return entries

    def invalidate(self) -> None:
        self._index.clear()

    async def candidates(self, *, question_text: str, options: list[dict[str, Any]] | None = None,
                         correct_concept_id: str | None = None, language: str = "en",
                         exclude_gid: str | None = None, limit: int = 10) -> dict[str, Any]:
        from app.questions.models import OptionText, concept_hash, text_hash

        config = await self._c.config.get()
        threshold = config.content.near_duplicate_threshold
        found: dict[str, dict[str, Any]] = {}
        if options:
            exact = text_hash(question_text, [OptionText(**o) for o in options])
            for row in await self._c.store.query(Query("question_translations").filter("text_hash", "==", exact)):
                gid = row.data["question_group_id"]
                if gid != exclude_gid:
                    found[gid] = {"question_group_id": gid, "kind": "EXACT", "score": 1.0}
        if correct_concept_id:
            fact = concept_hash(question_text, correct_concept_id)
            for row in await self._c.store.query(Query("question_groups").filter("concept_hash", "==", fact)):
                if row.id != exclude_gid:
                    found.setdefault(row.id, {"question_group_id": row.id, "kind": "CONCEPT", "score": 1.0})
        probe = embed(question_text)
        for entry in await self._entries(language):
            if entry.gid == exclude_gid or entry.gid in found:
                continue
            score = cosine(probe, entry.vector)
            if score >= threshold:
                found[entry.gid] = {"question_group_id": entry.gid, "kind": "SEMANTIC", "score": round(score, 4),
                                    "text": entry.text}
        ranked = sorted(found.values(), key=lambda d: -d["score"])[:limit]
        return {"threshold": threshold, "duplicates": ranked, "is_duplicate": bool(ranked)}
