"""Image question seed content and dev-server media delivery (spec §9.1, §22.2)."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.common.clock import FakeClock
from app.common.ids import sha256_hex
from app.common.media import DevMediaSigner, MemoryMediaUploader
from app.common.store.memory_docstore import MemoryDocStore
from app.container import Container
from app.main import create_app
from app.questions.models import (
    MEDIA_PREFERRED_MAX_BYTES,
    MEDIA_PREFERRED_MAX_DIMENSION,
    OptionText,
    QuestionStatus,
    QuestionTranslation,
    validate_competitive_text,
    webp_dimensions,
)
from app.questions.plan import bundle_problems
from app.questions.repository import QuestionRepository
from app.questions.seed import (
    MEDIA_FILES_DIR,
    SEED_LANGUAGES,
    import_seed,
    load_media_seed_items,
    seed_group_id,
)
from app.questions.taxonomy import is_valid_subcategory
from tests.conftest import make_settings


def test_image_seed_items_are_valid_and_files_meet_media_rules():
    items = load_media_seed_items()
    assert len({i["key"] for i in items}) == len(items) >= 28
    assert sum(1 for i in items if i.get("media")) >= 20  # curated rows may be text-only
    for item in items:
        assert is_valid_subcategory(item["category_id"], item["subcategory_id"]), item["key"]
        for lang in SEED_LANGUAGES:
            translation = QuestionTranslation(
                question_group_id="g", question_version=1, language=lang, question_text=item["question"][lang],
                options=[OptionText(concept_id=o["concept_id"], text=o[lang]) for o in item["options"]])
            assert validate_competitive_text(translation, item["correct"]) == [], (item["key"], lang)
        if not item.get("media"):
            continue
        assert item["media"]["license"] and item["media"]["source"], item["key"]
        if item["media"]["copyright_status"] == "LICENSED":
            assert item["media"]["attribution"], item["key"]
        data = (MEDIA_FILES_DIR / item["media"]["file"]).read_bytes()
        width, height = webp_dimensions(data)
        assert len(data) <= MEDIA_PREFERRED_MAX_BYTES and max(width, height) <= MEDIA_PREFERRED_MAX_DIMENSION
        assert set(item["media"]["alt_text"]) == set(SEED_LANGUAGES)


def test_active_import_uploads_and_approves_media_so_questions_are_eligible():
    async def run():
        store, clock, uploader = MemoryDocStore(), FakeClock(), MemoryMediaUploader()
        repo = QuestionRepository(store, clock)
        items = load_media_seed_items()
        result = await import_seed(repo, store, QuestionStatus.ACTIVE, items=[], uploader=uploader,
                                   now_ms=clock.now_ms())
        again = await import_seed(repo, store, QuestionStatus.ACTIVE, items=[], uploader=uploader)
        bundles = await repo.load_bundles([(seed_group_id(i["key"]), 1) for i in items], "tr")
        return result, again, bundles, uploader, clock.now_ms()

    result, again, bundles, uploader, now = asyncio.run(run())
    with_media = sum(1 for i in load_media_seed_items() if i.get("media"))
    assert result == {"created": len(bundles), "skipped": 0} and again == {"created": 0, "skipped": len(bundles)}
    assert len(uploader.objects) == with_media
    for bundle in bundles:
        if bundle.media is None:
            assert bundle_problems(bundle, now, "QUICK") == []
            continue
        assert bundle.media["review_status"] == "APPROVED"
        assert bundle.media["storage_path"] in uploader.objects
        assert bundle_problems(bundle, now, "QUICK") == []


def test_pending_import_keeps_media_pending_for_review():
    async def run():
        store, clock = MemoryDocStore(), FakeClock()
        repo = QuestionRepository(store, clock)
        await import_seed(repo, store, QuestionStatus.VALIDATION_PENDING, items=[], uploader=MemoryMediaUploader())
        return await store.get(f"media_assets/seedmedia_{sha256_hex('geography_img_001')[:20]}")

    assert asyncio.run(run())["review_status"] == "PENDING"


def test_text_only_import_without_uploader_skips_image_questions():
    async def run():
        store, clock = MemoryDocStore(), FakeClock()
        repo = QuestionRepository(store, clock)
        await import_seed(repo, store, QuestionStatus.ACTIVE, items=[])
        return await repo.get_group(seed_group_id("geography_img_001"))

    assert asyncio.run(run()) is None


def _dev_client() -> tuple[TestClient, Container]:
    container = Container(make_settings(env="dev", dev_media_base_url="http://10.0.2.2:8000"), clock=FakeClock())
    return TestClient(create_app(container)), container


def test_dev_server_serves_signed_media_until_expiry():
    client, container = _dev_client()
    with client:
        assert isinstance(container.media_signer, DevMediaSigner)
        path = next(iter(container.media_uploader.objects))
        now = container.clock.now_ms()
        url = asyncio.run(container.media_signer.sign(path, now + 60_000))
        assert url.startswith("http://10.0.2.2:8000/dev/media/")
        local = url.removeprefix("http://10.0.2.2:8000")
        ok = client.get(local)
        assert ok.status_code == 200 and ok.headers["content-type"] == "image/webp" and ok.content[8:12] == b"WEBP"
        expired = asyncio.run(container.media_signer.sign(path, now - 1)).removeprefix("http://10.0.2.2:8000")
        assert client.get(expired).status_code == 403
        assert client.get("/dev/media/questions%2Fnope%2Fv1%2Fmain.webp?exp=" + str(now + 1000)).status_code == 404


def test_dev_media_route_is_disabled_outside_the_dev_memory_server(client, clock):
    assert client.get(f"/dev/media/anything?exp={clock.now_ms() + 1000}").status_code == 404
