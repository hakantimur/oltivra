"""Versioned compressed pool manifests (spec §12.1).

A manifest lists lightweight selection metadata for competitive-eligible question versions of one
language/mode/difficulty. It never contains answer keys, source references or delivery URLs.
Storage: ``pool_manifest_versions/{language}_{mode}_{difficulty}`` (server-only version record) and
``pool_manifest_chunks/{key}_v{version}_{index}`` (gzip+base64 JSON chunks).
"""

from __future__ import annotations

import base64
import gzip
import json
import time
from dataclasses import asdict, dataclass

from app.common.clock import Clock
from app.common.store.docstore import DocStore, Query
from app.questions.models import COMPETITIVE_MODES, Difficulty, QuestionStatus, competitive_eligibility

CHUNK_ENTRIES = 4000


@dataclass(frozen=True)
class ManifestEntry:
    qid: int
    gid: str
    v: int
    cat: str
    sub: str
    d: str
    m: bool  # requires media


def manifest_key(language: str, mode: str, difficulty: str) -> str:
    return f"{language}_{mode}_{difficulty}"


def _encode(entries: list[ManifestEntry]) -> str:
    raw = json.dumps([asdict(e) for e in entries], separators=(",", ":")).encode()
    return base64.b64encode(gzip.compress(raw, mtime=0)).decode()


def _decode(blob: str) -> list[ManifestEntry]:
    return [ManifestEntry(**e) for e in json.loads(gzip.decompress(base64.b64decode(blob)))]


class ManifestBuilder:
    def __init__(self, store: DocStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    async def build_all(self, languages: list[str]) -> dict[str, int]:
        """Rebuild every manifest for the given languages; returns key -> entry count."""
        groups = await self._store.query(Query("question_groups").filter("status", "==", QuestionStatus.ACTIVE.value))
        now = self._clock.now_ms()
        buckets: dict[str, list[ManifestEntry]] = {}
        for language in languages:
            for mode in COMPETITIVE_MODES:
                for difficulty in Difficulty:
                    buckets[manifest_key(language, mode, difficulty.value)] = []
        media_ids = sorted({g.data["media_asset_id"] for g in groups if g.data.get("media_asset_id")})
        media_docs = dict(zip(media_ids, await self._store.get_many([f"media_assets/{m}" for m in media_ids]),
                              strict=True)) if media_ids else {}
        for language in languages:
            paths = [f"question_translations/{g.id}_{language}_{g.data['version']}" for g in groups]
            translations = await self._store.get_many(paths) if paths else []
            for group, translation in zip(groups, translations, strict=True):
                data = group.data
                media = media_docs.get(data.get("media_asset_id")) if data.get("media_asset_id") else None
                for mode in COMPETITIVE_MODES:
                    if competitive_eligibility(data, translation, now, media, mode):
                        continue
                    entry = ManifestEntry(qid=data["qid"], gid=group.id, v=data["version"], cat=data["category_id"],
                                          sub=data["subcategory_id"], d=data["declared_difficulty"],
                                          m=bool(data.get("media_asset_id")))
                    buckets[manifest_key(language, mode, entry.d)].append(entry)
        counts: dict[str, int] = {}
        for key, entries in buckets.items():
            entries.sort(key=lambda e: e.qid)
            await self._publish(key, entries)
            counts[key] = len(entries)
        return counts

    async def _publish(self, key: str, entries: list[ManifestEntry]) -> int:
        version_path = f"pool_manifest_versions/{key}"
        current = await self._store.get(version_path)
        version = (current["version"] + 1) if current else 1
        chunks = [entries[i:i + CHUNK_ENTRIES] for i in range(0, len(entries), CHUNK_ENTRIES)] or [[]]
        for index, chunk in enumerate(chunks):
            await self._store.set(f"pool_manifest_chunks/{key}_v{version}_{index}",
                                  {"schema_version": 1, "blob": _encode(chunk), "count": len(chunk)})
        await self._store.set(version_path, {
            "schema_version": 1, "key": key, "version": version, "chunk_count": len(chunks),
            "count": len(entries), "built_at_ms": self._clock.now_ms(),
        })
        if current:  # old chunks are unreachable once the pointer moves
            for index in range(current.get("chunk_count", 0)):
                await self._store.delete(f"pool_manifest_chunks/{key}_v{current['version']}_{index}")
        return version


class ManifestCache:
    """Per-instance in-memory manifest cache with version checking."""

    def __init__(self, store: DocStore, check_interval_s: float = 5.0) -> None:
        self._store = store
        self._interval = check_interval_s
        self._entries: dict[str, tuple[int, list[ManifestEntry]]] = {}
        self._checked: dict[str, float] = {}

    async def get(self, language: str, mode: str, difficulty: str) -> list[ManifestEntry]:
        key = manifest_key(language, mode, difficulty)
        cached = self._entries.get(key)
        if cached and time.monotonic() - self._checked.get(key, 0) < self._interval:
            return cached[1]
        pointer = await self._store.get(f"pool_manifest_versions/{key}")
        self._checked[key] = time.monotonic()
        if not pointer:
            self._entries[key] = (0, [])
            return []
        if cached and cached[0] == pointer["version"]:
            return cached[1]
        docs = await self._store.get_many([f"pool_manifest_chunks/{key}_v{pointer['version']}_{i}"
                                           for i in range(pointer["chunk_count"])])
        entries: list[ManifestEntry] = []
        for doc in docs:
            if doc is None:  # a concurrent rebuild removed this version; retry on next call
                self._checked.pop(key, None)
                return cached[1] if cached else []
            entries.extend(_decode(doc["blob"]))
        self._entries[key] = (pointer["version"], entries)
        return entries

    def invalidate(self) -> None:
        self._entries.clear()
        self._checked.clear()
