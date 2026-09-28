"""Admin API (spec §11): access control, question lifecycle, translations, duplicates, media, catalogs,
versioned config, pool health and the audit log."""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.main import create_app
from tests.conftest import Api, make_settings
from tests.helpers import seeded_store

ADMIN = "admin1"
AS_ADMIN = ":admin:mfa"


def options(prefix: str = "") -> list[dict]:
    return [{"concept_id": f"c_{i}", "text": f"{prefix}Option {name}"}
            for i, name in enumerate(("Alpha", "Bravo", "Charlie", "Delta"))]


def question_body(text: str = "Which river flows through the city of Vienna?", **overrides) -> dict:
    body = {"category_id": "geography", "subcategory_id": "countries", "difficulty": "MEDIUM",
            "global_relevance_score": 5, "canonical_language": "en",
            "translations": [{"language": "en", "question_text": text, "options": options()}],
            "correct_concept_id": "c_0", "source_refs": ["https://example.org/source"]}
    body.update(overrides)
    return body


def create(api: Api, text: str = "Which river flows through the city of Vienna?", **overrides) -> dict:
    res = api.post("/admin/v1/questions", ADMIN, question_body(text, **overrides), extra=AS_ADMIN)
    assert res.status_code == 200, res.text
    return res.json()


def activate(api: Api, gid: str) -> None:
    for target in ("VALIDATION_PENDING", "VERIFIED", "ACTIVE"):
        res = api.post(f"/admin/v1/questions/{gid}/transition", ADMIN, {"target": target, "reason": "review ok"},
                       extra=AS_ADMIN)
        assert res.status_code == 200, res.text


# ---------------------------------------------------------------------------------------------- access


def test_non_admin_is_forbidden(api):
    res = api.get("/admin/v1/questions", "u1")
    assert res.status_code == 403 and res.json()["error"]["detail"]["reason"] == "admin_required"
    assert api.get("/admin/v1/questions", None).status_code == 401


def test_mfa_required_when_configured(clock):
    settings = make_settings(admin_require_mfa=True)
    from app.common.store.livestore import MemoryLiveStore
    from app.common.tasks import RecordingScheduler

    container = Container(settings, clock=clock, store=seeded_store(), live=MemoryLiveStore(settings.shard_ids),
                          tasks=RecordingScheduler())
    with TestClient(create_app(container)) as client:
        api = Api(client)
        res = api.get("/admin/v1/questions", ADMIN, extra=":admin")
        assert res.status_code == 403 and res.json()["error"]["detail"]["reason"] == "mfa_required"
        assert api.get("/admin/v1/questions", ADMIN, extra=AS_ADMIN).status_code == 200


# ---------------------------------------------------------------------------------------------- questions


async def test_create_verify_activate_enters_manifest_and_audit(api, container):
    group = create(api)["group"]
    gid = group["id"]
    assert group["status"] == "DRAFT"
    activate(api, gid)
    detail = api.get(f"/admin/v1/questions/{gid}", ADMIN, extra=AS_ADMIN).json()
    assert detail["group"]["status"] == "ACTIVE" and detail["group"]["competitive_enabled"]
    assert detail["private"]["verified_by"] == ADMIN
    assert sorted(h["to"] for h in detail["status_history"]) == ["ACTIVE", "VALIDATION_PENDING", "VERIFIED"]
    container.manifest_cache.invalidate()
    entries = await container.manifest_cache.get("en", "QUICK", "MEDIUM")
    assert group["qid"] not in {e.qid for e in entries}  # the translation itself is still unverified
    assert api.post(f"/admin/v1/questions/{gid}/translations/en/verify", ADMIN, extra=AS_ADMIN).status_code == 200
    container.manifest_cache.invalidate()
    entries = await container.manifest_cache.get("en", "QUICK", "MEDIUM")
    assert group["qid"] in {e.qid for e in entries}
    audit = api.get("/admin/v1/audit", ADMIN, extra=AS_ADMIN, subject=f"question:{gid}").json()["entries"]
    assert {e["action"] for e in audit} >= {"QUESTION_CREATE", "QUESTION_VERIFIED", "QUESTION_ACTIVE"}
    assert all(e["actor"] == ADMIN for e in audit)


def test_list_filters_and_search(api):
    gid = create(api)["group"]["id"]
    create(api, "What is the tallest mountain on the African continent?", difficulty="HARD")
    listed = api.get("/admin/v1/questions", ADMIN, extra=AS_ADMIN, status="DRAFT", difficulty="MEDIUM").json()
    assert gid in {i["question_group_id"] for i in listed["items"]}
    assert all(i["difficulty"] == "MEDIUM" for i in listed["items"])
    found = api.get("/admin/v1/questions", ADMIN, extra=AS_ADMIN, q="vienna").json()["items"]
    assert gid in [i["question_group_id"] for i in found]
    assert all("vienna" in (i["text"] or "").lower() for i in found)


def test_invalid_transition_and_unknown_category(api):
    gid = create(api)["group"]["id"]
    res = api.post(f"/admin/v1/questions/{gid}/transition", ADMIN, {"target": "ACTIVE", "reason": "skip"},
                   extra=AS_ADMIN)
    assert res.status_code == 409
    res = api.post("/admin/v1/questions", ADMIN, question_body(category_id="astrology"), extra=AS_ADMIN)
    assert res.status_code == 400 and res.json()["error"]["detail"]["reason"] == "unknown_category"


async def test_new_version_leaves_pool_until_reverified(api, container):
    group = create(api, translations=[{"language": "en", "verified": True, "question_text":
                                       "Which river flows through the city of Vienna?", "options": options()}])["group"]
    activate(api, group["id"])
    assert group["qid"] in {e.qid for e in await container.manifest_cache.get("en", "QUICK", "MEDIUM")}
    body = {"translations": [{"language": "en", "question_text": "Which river flows through Vienna, Austria?",
                              "options": options()}], "correct_concept_id": "c_0", "source_refs": []}
    res = api.post(f"/admin/v1/questions/{group['id']}/versions", ADMIN, body, extra=AS_ADMIN)
    assert res.status_code == 200 and res.json()["group"]["version"] == 2
    container.manifest_cache.invalidate()
    entries = await container.manifest_cache.get("en", "QUICK", "MEDIUM")
    assert group["qid"] not in {e.qid for e in entries}
    bad = api.post(f"/admin/v1/questions/{group['id']}/versions", ADMIN, {**body, "changes": {"qid": 1}},
                   extra=AS_ADMIN)
    assert bad.status_code == 400


def test_translation_upsert_rules(api):
    gid = create(api)["group"]["id"]
    tr = {"language": "tr", "question_text": "Viyana şehrinden hangi nehir geçer?", "options": options("TR ")}
    res = api.put(f"/admin/v1/questions/{gid}/translations/tr", ADMIN, tr, extra=AS_ADMIN)
    assert res.status_code == 200 and res.json()["translation"]["problems"] == []
    wrong = {**tr, "options": [{**o, "concept_id": f"x_{i}"} for i, o in enumerate(tr["options"])]}
    res = api.put(f"/admin/v1/questions/{gid}/translations/tr", ADMIN, wrong, extra=AS_ADMIN)
    assert res.json()["error"]["detail"]["reason"] == "concepts_must_match_version"
    assert api.post(f"/admin/v1/questions/{gid}/translations/tr/verify", ADMIN, extra=AS_ADMIN).status_code == 200
    res = api.put(f"/admin/v1/questions/{gid}/translations/tr", ADMIN, tr, extra=AS_ADMIN)
    assert res.status_code == 409
    mismatch = api.put(f"/admin/v1/questions/{gid}/translations/de", ADMIN, tr, extra=AS_ADMIN)
    assert mismatch.json()["error"]["detail"]["reason"] == "language_mismatch"
    detail = api.get(f"/admin/v1/questions/{gid}", ADMIN, extra=AS_ADMIN).json()
    assert {t["language"] for t in detail["translations"]} == {"en", "tr"}


def test_duplicate_detection_exact_concept_and_semantic(api):
    gid = create(api)["group"]["id"]
    exact = api.post("/admin/v1/duplicates/check", ADMIN,
                     {"question_text": "Which river flows through the city of Vienna?", "options": options()},
                     extra=AS_ADMIN).json()
    assert exact["duplicates"][0] == {"question_group_id": gid, "kind": "EXACT", "score": 1.0}
    semantic = api.post("/admin/v1/duplicates/check", ADMIN,
                        {"question_text": "Which river flows through the city of Vienna, Austria?"},
                        extra=AS_ADMIN).json()
    assert semantic["is_duplicate"] and semantic["duplicates"][0]["kind"] == "SEMANTIC"
    unrelated = api.post("/admin/v1/duplicates/check", ADMIN,
                         {"question_text": "How many strings does a standard violin have?"}, extra=AS_ADMIN).json()
    assert not unrelated["is_duplicate"]
    again = create(api)  # creating a near-copy reports the existing group
    assert gid in {d["question_group_id"] for d in again["duplicates"]["duplicates"]}


def test_validation_queue(api):
    gid = create(api, status="VALIDATION_PENDING")["group"]["id"]
    create(api, "What is the capital city of Canada?")
    queue = api.get("/admin/v1/validation-queue", ADMIN, extra=AS_ADMIN).json()["items"]
    assert [i["question_group_id"] for i in queue] == [gid]


# ---------------------------------------------------------------------------------------------- media


def media_payload(gid: str, version: int = 1, data: bytes = b"RIFF\x10\x00\x00\x00WEBPVP8 fake", **extra) -> dict:
    return {"question_group_id": gid, "version": version, "content_type": "image/webp",
            "data_base64": base64.b64encode(data).decode(), "width": 640, "height": 480,
            "alt_text": {"en": "A river"}, "source": "own photo", "license": "CC0", "copyright_status": "CLEARED",
            **extra}


def test_media_upload_and_review(api, container):
    gid = create(api)["group"]["id"]
    res = api.post("/admin/v1/media", ADMIN, media_payload(gid), extra=AS_ADMIN)
    assert res.status_code == 200, res.text
    media = res.json()["media"]
    assert media["review_status"] == "PENDING" and res.json()["warnings"] == []
    assert media["storage_path"] == f"questions/{gid}/v1/main.webp" and media["preferred_limits_ok"] is True
    assert container.media_uploader.objects[media["storage_path"]][0].startswith(b"RIFF")
    assert "immutable" in container.media_uploader.cache_control[media["storage_path"]]
    assert container.store._docs[f"question_groups/{gid}"]["media_asset_id"] == media["id"]
    assert container.store._docs[f"question_versions/{gid}_1"]["snapshot"]["media_asset_id"] == media["id"]
    res = api.patch(f"/admin/v1/media/{media['id']}", ADMIN, {"review_status": "APPROVED"}, extra=AS_ADMIN)
    assert res.json()["media"]["review_status"] == "APPROVED"
    pending = api.get("/admin/v1/media", ADMIN, extra=AS_ADMIN, review_status="PENDING").json()["items"]
    assert pending == []
    bad = api.post("/admin/v1/media", ADMIN, {**media_payload(gid), "data_base64": "not base64!"}, extra=AS_ADMIN)
    assert bad.status_code == 400


def test_media_is_webp_versioned_and_never_overwritten(api, container):
    gid = create(api)["group"]["id"]
    png = api.post("/admin/v1/media", ADMIN, media_payload(gid, data=b"PNG_HEADER" + b"0" * 16),
                   extra=AS_ADMIN)
    assert png.status_code == 400 and png.json()["error"]["detail"]["reason"] == "not_webp"
    jpeg = api.post("/admin/v1/media", ADMIN, media_payload(gid, content_type="image/jpeg"), extra=AS_ADMIN)
    assert jpeg.status_code == 422 or jpeg.status_code == 400
    big = media_payload(gid, data=b"RIFF\x10\x00\x00\x00WEBP" + b"0" * 250_000, width=2000, height=1000)
    res = api.post("/admin/v1/media", ADMIN, big, extra=AS_ADMIN)
    assert res.status_code == 200
    assert set(res.json()["warnings"]) == {"above_preferred_bytes", "above_preferred_dimension"}
    assert res.json()["media"]["preferred_limits_ok"] is False
    # The same version path is never overwritten in place.
    again = api.post("/admin/v1/media", ADMIN, media_payload(gid), extra=AS_ADMIN)
    assert again.status_code == 409 and again.json()["error"]["detail"]["reason"] == "media_exists"
    # A stale or verified version is immutable.
    stale = api.post("/admin/v1/media", ADMIN, media_payload(gid, version=2), extra=AS_ADMIN)
    assert stale.json()["error"]["detail"]["reason"] == "version_immutable"
    active = create(api, "What is the capital city of Canada?")["group"]["id"]
    activate(api, active)
    locked = api.post("/admin/v1/media", ADMIN, media_payload(active), extra=AS_ADMIN)
    assert locked.status_code == 409 and locked.json()["error"]["detail"]["reason"] == "version_immutable"


# ---------------------------------------------------------------------------------------------- catalog/config


def test_category_override_visible_to_clients(api):
    res = api.put("/admin/v1/categories/geography", ADMIN,
                  {"names": {"en": "World Geography"}, "disabled_subcategories": ["flags"]}, extra=AS_ADMIN)
    assert res.status_code == 200
    category = res.json()["category"]
    assert category["names"]["en"] == "World Geography" and "flags" not in category["subcategories"]
    assert api.put("/admin/v1/categories/astrology", ADMIN, {"names": {"en": "x"}}, extra=AS_ADMIN).status_code == 404
    api.onboard("u1")
    client_view = api.get("/v1/categories", "u1").json()
    geography = next(c for c in client_view["categories"] if c["id"] == "geography")
    assert geography["name"] == "World Geography"
    assert "flags" not in {sub["id"] for sub in geography["subcategories"]}


def test_config_publish_is_versioned_and_ranked_never_weaker(api, container):
    before = api.get("/admin/v1/config", ADMIN, extra=AS_ADMIN).json()["active"]["config_version"]
    res = api.post("/admin/v1/config", ADMIN, {"config": {"ranked": {"quick_min_other_humans": 1}},
                                               "reason": "try weaker"}, extra=AS_ADMIN)
    assert res.status_code == 400 and res.json()["error"]["detail"]["reason"] == "invalid_config"
    res = api.post("/admin/v1/config", ADMIN, {"config": {"content": {"near_duplicate_threshold": 0.9}},
                                               "reason": "tighten duplicates"}, extra=AS_ADMIN)
    assert res.status_code == 200 and res.json()["config_version"] == before + 1
    view = api.get("/admin/v1/config", ADMIN, extra=AS_ADMIN).json()
    assert view["active"]["content"]["near_duplicate_threshold"] == 0.9
    assert view["versions"][0]["reason"] == "tighten duplicates"


def test_bot_avatar_and_reaction_catalogs(api, container):
    bots = api.get("/admin/v1/bots", ADMIN, extra=AS_ADMIN).json()
    assert len(bots["bots"]) == 150 and "NORMAL" in bots["profiles"]
    bot_id = bots["bots"][0]["bot_id"]
    res = api.put(f"/admin/v1/bots/{bot_id}", ADMIN, {"username": "river_fox", "profile": "STRONG"}, extra=AS_ADMIN)
    assert res.status_code == 200, res.text
    assert container.store._docs["username_registry/river_fox"]["uid"] == f"bot:{bot_id}"
    api.onboard("u1")
    taken = api.post("/v1/profile/username", "u1", {"username": "river_fox"})
    assert taken.status_code == 409
    avatar = api.put("/admin/v1/avatars/av_new", ADMIN, {"motif": "star", "bg": "#000000", "fg": "#ffffff",
                                                         "accent": "#ff0000"}, extra=AS_ADMIN)
    assert avatar.status_code == 200
    assert "av_new" in {a["id"] for a in api.get("/v1/avatars", "u1").json()["avatars"]}
    reaction = api.put("/admin/v1/reactions/wow", ADMIN, {"kind": "EMOJI", "display": "😮",
                                                          "labels": {"en": "Wow"}}, extra=AS_ADMIN)
    assert reaction.status_code == 200
    incomplete = api.put("/admin/v1/reactions/meh", ADMIN, {"kind": "EMOJI"}, extra=AS_ADMIN)
    assert incomplete.status_code == 400


def test_pool_health_report(api):
    report = api.get("/admin/v1/pool-health", ADMIN, extra=AS_ADMIN, language="en", trials=20).json()
    assert report["language"] == "en" and set(report["per_difficulty"]) == {"EASY", "MEDIUM", "HARD"}
    assert set(report["language_gate"]) == {"soft_launch", "full_scale"}
    total = sum(report["per_difficulty"].values())
    assert report["language_gate"]["soft_launch"]["checks"]["total_active_groups"] == (total >= 6000)
    assert 0.0 <= report["simulation"]["quick_success_rate"] <= 1.0


@pytest.mark.parametrize("path", ["/admin/v1/bots", "/admin/v1/config", "/admin/v1/categories", "/admin/v1/audit"])
def test_admin_reads_forbidden_for_players(api, path):
    assert api.get(path, "u1").status_code == 403
