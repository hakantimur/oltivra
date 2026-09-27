"""Curated question seed and the dormant media path (spec §9.1, §22.2).

Since the 2026-09-27 playtest the curated set is text-only; the image pipeline stays supported so it can be
switched back on without code changes.
"""

from __future__ import annotations

import asyncio
import io

from fastapi.testclient import TestClient
from PIL import Image

from app.common.clock import FakeClock
from app.common.media import DevMediaSigner, MemoryMediaUploader
from app.common.store.memory_docstore import MemoryDocStore
from app.container import Container
from app.main import create_app
from app.questions import seed
from app.questions.models import OptionText, QuestionStatus, QuestionTranslation, validate_competitive_text
from app.questions.plan import bundle_problems
from app.questions.repository import QuestionRepository
from app.questions.seed import SEED_LANGUAGES, import_seed, load_media_seed_items, seed_group_id
from app.questions.taxonomy import is_valid_subcategory
from tests.conftest import make_settings


def _webp() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 48), (40, 120, 200)).save(out, "WEBP")
    return out.getvalue()


def _media_item(key: str = "test_img_001") -> dict:
    return {
        "key": key, "category_id": "geography", "subcategory_id": "landmarks", "difficulty": "EASY",
        "global_relevance_score": 5, "time_sensitive": False,
        "question": {"en": "Which river flows through this city?", "tr": "Bu şehirden hangi nehir geçer?"},
        "options": [{"concept_id": c, "en": c.title(), "tr": c.title()} for c in ("seine", "thames", "tiber", "rhine")],
        "correct": "seine", "source": "https://en.wikipedia.org/wiki/Seine",
        "media": {"file": "test/img.webp", "alt_text": {"en": "A river", "tr": "Bir nehir"},
                  "source": "own", "license": "CC0", "copyright_status": "PUBLIC_DOMAIN"},
    }


def test_curated_items_are_valid_text_questions():
    items = load_media_seed_items()
    assert len(items) >= 25 and len({i["key"] for i in items}) == len(items)
    for item in items:
        assert "media" not in item and "image" not in item, item["key"]  # no image questions (playtest decision)
        assert is_valid_subcategory(item["category_id"], item["subcategory_id"]), item["key"]
        assert item["source"].startswith("https://en.wikipedia.org/wiki/"), item["key"]
        for lang in SEED_LANGUAGES:
            translation = QuestionTranslation(
                question_group_id="g", question_version=1, language=lang, question_text=item["question"][lang],
                options=[OptionText(concept_id=o["concept_id"], text=o[lang]) for o in item["options"]])
            assert validate_competitive_text(translation, item["correct"]) == [], (item["key"], lang)


def test_active_import_makes_curated_questions_eligible():
    async def run():
        store, clock = MemoryDocStore(), FakeClock()
        repo = QuestionRepository(store, clock)
        items = load_media_seed_items()
        result = await import_seed(repo, store, QuestionStatus.ACTIVE, items=[], now_ms=clock.now_ms())
        again = await import_seed(repo, store, QuestionStatus.ACTIVE, items=[])
        bundles = await repo.load_bundles([(seed_group_id(i["key"]), 1) for i in items], "tr")
        return result, again, bundles, clock.now_ms()

    result, again, bundles, now = asyncio.run(run())
    assert result == {"created": len(bundles), "skipped": 0} and again == {"created": 0, "skipped": len(bundles)}
    assert all(bundle_problems(b, now, "QUICK") == [] and b.media is None for b in bundles)


def test_media_item_upload_is_approved_when_active_and_pending_otherwise(tmp_path, monkeypatch):
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "img.webp").write_bytes(_webp())
    monkeypatch.setattr(seed, "MEDIA_FILES_DIR", tmp_path)

    async def run(status, key):
        store, clock, uploader = MemoryDocStore(), FakeClock(), MemoryMediaUploader()
        repo = QuestionRepository(store, clock)
        await import_seed(repo, store, status, items=[], media_items=[_media_item(key)], uploader=uploader,
                          now_ms=clock.now_ms())
        bundle = (await repo.load_bundles([(seed_group_id(key), 1)], "en"))
        media = await store.get(f"media_assets/seedmedia_{seed.sha256_hex(key)[:20]}")
        return bundle, media, uploader, clock.now_ms()

    bundles, media, uploader, now = asyncio.run(run(QuestionStatus.ACTIVE, "test_img_001"))
    assert media["review_status"] == "APPROVED" and media["storage_path"] in uploader.objects
    assert bundle_problems(bundles[0], now, "QUICK") == []
    _, pending, _, _ = asyncio.run(run(QuestionStatus.VALIDATION_PENDING, "test_img_002"))
    assert pending["review_status"] == "PENDING"


def test_media_item_is_skipped_without_an_uploader(tmp_path, monkeypatch):
    monkeypatch.setattr(seed, "MEDIA_FILES_DIR", tmp_path)

    async def run():
        store, clock = MemoryDocStore(), FakeClock()
        repo = QuestionRepository(store, clock)
        await import_seed(repo, store, QuestionStatus.ACTIVE, items=[], media_items=[_media_item()])
        return await repo.get_group(seed_group_id("test_img_001"))

    assert asyncio.run(run()) is None


def test_dev_server_serves_signed_media_until_expiry():
    container = Container(make_settings(env="dev", dev_media_base_url="http://10.0.2.2:8000"), clock=FakeClock())
    client = TestClient(create_app(container))
    with client:
        assert isinstance(container.media_signer, DevMediaSigner)
        path = "questions/gtest/v1/main.webp"
        asyncio.run(container.media_uploader.put(path, _webp(), "image/webp"))
        now = container.clock.now_ms()
        url = asyncio.run(container.media_signer.sign(path, now + 60_000))
        assert url.startswith("http://10.0.2.2:8000/dev/media/")
        ok = client.get(url.removeprefix("http://10.0.2.2:8000"))
        assert ok.status_code == 200 and ok.headers["content-type"] == "image/webp" and ok.content[8:12] == b"WEBP"
        expired = asyncio.run(container.media_signer.sign(path, now - 1)).removeprefix("http://10.0.2.2:8000")
        assert client.get(expired).status_code == 403
        assert client.get("/dev/media/questions%2Fnope%2Fv1%2Fmain.webp?exp=" + str(now + 1000)).status_code == 404


def test_dev_media_route_is_disabled_outside_the_dev_memory_server(client, clock):
    assert client.get(f"/dev/media/anything?exp={clock.now_ms() + 1000}").status_code == 404


async def test_retire_tool_removes_questions_from_the_pool(container):
    from tools.content.retire import retire

    key = load_media_seed_items()[0]["key"]
    gid = seed_group_id(key)
    report = await retire(container, [key, "no_such_key"], "test")
    assert report["retired"] == [key] and report["missing"] == ["no_such_key"]
    assert (await retire(container, [key], "test"))["already_retired"] == [key]
    group = await container.question_repo.get_group(gid)
    assert group["status"] == "RETIRED" and group["competitive_enabled"] is False
    container.manifest_cache.invalidate()
    for difficulty in ("EASY", "MEDIUM", "HARD"):
        assert gid not in {e.gid for e in await container.manifest_cache.get("en", "QUICK", difficulty)}
