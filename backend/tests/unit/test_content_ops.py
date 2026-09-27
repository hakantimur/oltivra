"""AI generation pipeline, maintenance jobs and the external web deletion path (spec §11.1, §20.6, §30.1)."""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx
import pytest

from app.admin.ai_generation import (
    AnthropicQuestionGenerator,
    FakeQuestionGenerator,
    GenerationSpec,
    normalise_candidate,
)
from app.common.clock import iso_week_id, next_iso_week_start_ms
from app.common.store.docstore import Query
from app.common.tasks import TaskKind
from tests.unit.test_matchmaking import join, run_tasks

ADMIN = "admin1"
AS_ADMIN = ":admin:mfa"
INTERNAL = {"x-internal-auth": "dev-internal-secret"}


def job_body(**overrides) -> dict:
    body = {"category_id": "arts_literature", "subcategory_id": "famous_works", "difficulty": "MEDIUM",
            "canonical_language": "en", "required_languages": ["tr"], "count": 8}
    body.update(overrides)
    return body


def create_job(api, **overrides) -> dict:
    res = api.post("/admin/v1/ai-jobs", ADMIN, job_body(**overrides), extra=AS_ADMIN)
    assert res.status_code == 200, res.text
    return res.json()["job"]


def job(api, job_id) -> dict:
    return api.get(f"/admin/v1/ai-jobs/{job_id}", ADMIN, extra=AS_ADMIN).json()["job"]


def reasons(done: dict) -> dict[int, list[str]]:
    return {r["index"]: r["reasons"] for r in done["rejected"]}


# ---------------------------------------------------------------------------------------------- AI generation


def test_ai_job_runs_full_pipeline(api, container):
    created = create_job(api)
    assert created["status"] == "QUEUED" and created["prompt_version"] == "qgen-v1"
    assert created["spec"]["min_global_relevance"] == 4  # never weaker than versioned config
    assert [t.kind for t in container.tasks.pending()] == [TaskKind.QUESTION_BATCH]
    run_tasks(container)
    done = job(api, created["job_id"])
    assert done["status"] == "COMPLETED" and len(done["accepted"]) == 2
    assert reasons(done) == {
        2: ["semantic_duplicate_in_batch"],
        3: ["low_global_relevance"],
        4: ["correct_not_in_options"],
        5: ["translation_missing_tr"],
        6: ["option_too_long_en", "option_too_long_tr"],
        7: ["no_source"],
    }
    detail = api.get(f"/admin/v1/questions/{done['accepted'][0]}", ADMIN, extra=AS_ADMIN).json()
    group = detail["group"]
    assert group["status"] == "GENERATED" and not group["verified"] and not group["competitive_enabled"]
    assert group["ai"] == {"provider": "fake", "model": "scripted-v1", "prompt_version": "qgen-v1",
                           "job_id": created["job_id"], "candidate_index": 0, "sources_unverified": True}
    assert {t["language"] for t in detail["translations"]} == {"en", "tr"}
    assert not any(t["translation_verified"] for t in detail["translations"])
    queue = api.get("/admin/v1/validation-queue", ADMIN, extra=AS_ADMIN).json()["items"]
    assert set(done["accepted"]) <= {i["question_group_id"] for i in queue}
    listed = api.get("/admin/v1/ai-jobs", ADMIN, extra=AS_ADMIN).json()["items"]
    assert listed[0]["accepted"] == 2 and listed[0]["rejected"] == 6


def test_ai_output_never_reaches_competitive_pool_automatically(api, container):
    create_job(api)
    run_tasks(container)
    container.manifest_cache.invalidate()
    entries = asyncio.run(container.manifest_cache.get("en", "QUICK", "MEDIUM"))
    groups = asyncio.run(container.store.query(Query("question_groups")))
    generated = {r.data["qid"] for r in groups if r.data.get("ai")}
    assert generated and not generated & {e.qid for e in entries}


def test_second_job_rejects_existing_facts_and_duplicate_task_is_noop(api, container):
    first = create_job(api)
    run_tasks(container)
    assert asyncio.run(container.ai_generation.run(first["job_id"])) == {"changed": False}
    second = create_job(api, count=2)
    run_tasks(container)
    done = job(api, second["job_id"])
    assert done["accepted"] == [] and reasons(done) == {0: ["exact_duplicate"], 1: ["exact_duplicate"]}


def test_semantic_duplicate_against_pool(api, container):
    create_job(api, count=2)
    run_tasks(container)
    paraphrase = {"question": {"en": "In which city is the Sagrada Familia basilica situated?"},
                  "options": [{"concept_id": c, "text": {"en": c.title()}} for c in ("barcelona", "rome", "oslo",
                                                                                       "porto")],
                  "correct_concept_id": "barcelona", "global_relevance_score": 5, "sources": ["https://x.org"]}
    container.ai_generation.generator = FakeQuestionGenerator([paraphrase])
    third = create_job(api, count=1, required_languages=[])
    run_tasks(container)
    done = job(api, third["job_id"])
    assert done["rejected"][0]["reasons"] == ["semantic_duplicate"] and done["rejected"][0]["duplicates"]


def test_job_validation(api):
    assert api.post("/admin/v1/ai-jobs", ADMIN, job_body(subcategory_id="nope"), extra=AS_ADMIN).status_code == 400
    res = api.post("/admin/v1/ai-jobs", ADMIN, job_body(count=26), extra=AS_ADMIN)
    assert res.json()["error"]["detail"] == {"reason": "too_many_candidates", "max": 25}
    assert api.post("/admin/v1/ai-jobs", "u1", job_body()).status_code == 403


class _Broken:
    provider, model = "fake", "broken"

    async def generate(self, spec, prompt_version):
        raise RuntimeError("provider down")


def test_provider_failure_retries_then_fails_and_admin_can_retry(api, container):
    container.ai_generation.generator = _Broken()
    created = create_job(api)
    for attempt in range(1, 4):
        if attempt < 3:
            with pytest.raises(RuntimeError):
                asyncio.run(container.ai_generation.run(created["job_id"]))
        else:
            assert asyncio.run(container.ai_generation.run(created["job_id"]))["status"] == "FAILED"
    failed = job(api, created["job_id"])
    assert failed["status"] == "FAILED" and failed["attempts"] == 3 and "provider down" in failed["error"]
    container.ai_generation.generator = FakeQuestionGenerator()
    res = api.post(f"/admin/v1/ai-jobs/{created['job_id']}/retry", ADMIN, extra=AS_ADMIN)
    assert res.json()["job"]["status"] == "QUEUED"
    container.tasks.tasks.clear()
    asyncio.run(container.ai_generation.run(created["job_id"]))
    assert job(api, created["job_id"])["status"] == "COMPLETED"
    again = api.post(f"/admin/v1/ai-jobs/{created['job_id']}/retry", ADMIN, extra=AS_ADMIN)
    assert again.status_code == 409


def test_anthropic_generator_uses_forced_tool_call():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"content": [
            {"type": "text", "text": "ok"},
            {"type": "tool_use", "name": "submit_questions", "input": {"questions": [{"question": {"en": "Q?"}}]}}]})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            gen = AnthropicQuestionGenerator("sk-test", "claude-sonnet-5", client)
            spec = GenerationSpec("music", "artists", "EASY", "en", ["tr", "de"], 3, 4)
            return await gen.generate(spec, "qgen-v1")

    batch = asyncio.run(scenario())
    assert batch.provider == "anthropic" and batch.model == "claude-sonnet-5"
    assert batch.candidates == [{"question": {"en": "Q?"}}]
    assert seen["headers"]["x-api-key"] == "sk-test" and seen["headers"]["anthropic-version"] == "2023-06-01"
    body = seen["body"]
    assert body["model"] == "claude-sonnet-5" and body["tool_choice"] == {"type": "tool", "name": "submit_questions"}
    schema = body["tools"][0]["input_schema"]["properties"]["questions"]["items"]["properties"]["question"]
    assert schema["required"] == ["de", "en", "tr"]
    with pytest.raises(ValueError):
        AnthropicQuestionGenerator("", "claude-sonnet-5")


def test_normalise_candidate():
    raw = {"question": {"en": "  Which   city?  ", "tr": ""}, "options": [{"concept_id": "New York!", "text":
           {"en": " New  York "}}], "correct_concept_id": "NEW YORK", "global_relevance_score": "x",
           "sources": [" ", "https://a"]}
    out = normalise_candidate(raw)
    assert out["question"] == {"en": "Which city?"} and out["options"][0] == {"concept_id": "new_york",
                                                                               "text": {"en": "New York"}}
    assert out["correct_concept_id"] == "new_york" and out["global_relevance_score"] == 0
    assert out["sources"] == ["https://a"]


# ---------------------------------------------------------------------------------------------- maintenance


def maintenance(client, job_name):
    return client.post(f"/internal/maintenance/{job_name}", headers=INTERNAL)


def test_maintenance_requires_service_auth(client):
    assert client.post("/internal/maintenance/expire-tickets").status_code in (401, 403)
    assert client.post("/internal/maintenance/expire-tickets",
                       headers={"authorization": "Bearer test:u1"}).status_code in (401, 403)
    assert maintenance(client, "nope").status_code == 404


def test_expire_tickets_and_sanctions(api, client, container):
    api.onboard("u1")
    assert join(api, "u1").json()["state"] == "QUEUED"
    container.clock.advance(10 * 60_000)
    res = maintenance(client, "expire-tickets").json()
    assert res["result"]["expired"] == 1
    assert container.store._docs["user_runtime/u1"]["state"] == "IDLE"
    assert maintenance(client, "expire-sanctions").json()["result"] == {"users_refreshed": 0}


def test_release_usernames_after_reservation(api, client, container):
    api.onboard("u1")
    container.clock.advance(31 * 86_400_000)
    assert api.post("/v1/profile/username/change", "u1", {"username": "brand_new"}).status_code == 200
    assert container.store._docs["username_registry/user_u1"]["state"] == "RESERVED"
    assert maintenance(client, "release-usernames").json()["result"]["released"] == 0
    container.clock.advance(30 * 86_400_000 + 1)
    assert maintenance(client, "release-usernames").json()["result"]["released"] == 1
    assert "username_registry/user_u1" not in container.store._docs


def test_sweep_stale_preparing_match_releases_players(api, client, container):
    api.onboard("u1")
    container.store._docs["match_index/m_stale"] = {
        "match_id": "m_stale", "state": "PREPARING", "rtdb_shard_id": container.settings.shard_ids[0],
        "participant_uids": ["u1"], "created_at_ms": container.clock.now_ms(), "mode": "QUICK"}
    container.store._docs["user_runtime/u1"] = {"uid": "u1", "state": "MATCH_ACTIVE", "active_match_id": "m_stale",
                                                "updated_at_ms": container.clock.now_ms()}
    assert maintenance(client, "sweep-stale-matches").json()["result"]["aborted"] == 0  # not stale yet
    container.clock.advance(3 * 60_000)
    assert maintenance(client, "sweep-stale-matches").json()["result"]["aborted"] == 1
    assert container.store._docs["match_index/m_stale"]["state"] == "CANCELLED"
    assert container.store._docs["user_runtime/u1"]["state"] == "IDLE"


def test_sweep_reschedules_lost_settlement(api, client, container, monkeypatch):
    from tests.unit.test_matchmaking import bot_fill_match, play_round_human_wins

    api.onboard("u1")
    match_id = bot_fill_match(api, container)

    async def lost(*args, **kwargs):  # the settlement task is lost in transit
        return None

    monkeypatch.setattr(container.settlement, "_schedule", lost)
    for _ in range(10):
        play_round_human_wins(api, container, match_id)
    assert container.store._docs[f"settlement_ledgers/{match_id}"]["status"] == "PENDING"
    monkeypatch.undo()
    container.clock.advance(2 * 60_000)
    res = maintenance(client, "sweep-stale-matches").json()["result"]
    assert res["settlement_rescheduled"] == 1
    run_tasks(container)
    assert container.store._docs[f"settlement_ledgers/{match_id}"]["status"] == "SETTLED"


def test_reminders_respect_timing_and_spacing(api, client, container):
    api.onboard("u1")
    api.post("/v1/devices", "u1", {"token": "fcm-token-u1-xxxxxxxx", "platform": "android"})
    api.get("/v1/missions/daily", "u1")  # creates today's mission document
    first = maintenance(client, "mission-reminders").json()["result"]
    assert first == {"sent": 1, "candidates": 1}
    assert maintenance(client, "mission-reminders").json()["result"]["sent"] == 0  # per-recipient spacing
    container.store._docs["weekly_user_stats/x_u1"] = {"uid": "u1", "week_id": iso_week_id(container.clock.now_ms())}
    now = container.clock.now_ms()
    if next_iso_week_start_ms(now) - now > 86_400_000:
        assert maintenance(client, "leaderboard-ending-reminders").json()["result"]["skipped"] == "not_final_day"
        container.clock.set(next_iso_week_start_ms(now) - 3_600_000)
        container.store._docs["weekly_user_stats/x_u1"]["week_id"] = iso_week_id(container.clock.now_ms())
    assert maintenance(client, "leaderboard-ending-reminders").json()["result"]["sent"] == 1


def test_rebuild_manifests_and_aggregate_stats(client, container):
    rebuilt = maintenance(client, "rebuild-manifests").json()["result"]
    assert rebuilt["manifests"] > 0 and rebuilt["entries"] > 0
    stats = maintenance(client, "aggregate-question-stats").json()["result"]
    assert stats["groups"] > 0 and stats["wrapped"] in (True, False)
    assert maintenance(client, "reconcile-purchases").json()["result"] == {"google_changed": 0,
                                                                            "apple_changed": 0}


# ---------------------------------------------------------------------------------------------- web deletion


def test_web_deletion_page_is_hardened(client):
    res = client.get("/account/delete")
    assert res.status_code == 200 and "Delete your Synova account" in res.text
    assert "default-src 'none'" in res.headers["content-security-policy"]
    assert res.headers["x-frame-options"] == "DENY" and res.headers["cache-control"] == "no-store"
    assert "demo-oltivra" in res.text and "</script><" not in res.text.split("const cfg =")[1][:300]


def test_web_deletion_requires_recent_login_and_confirmation(api, client, container):
    api.onboard("u1")
    body = {"request_id": str(uuid.uuid4()), "confirm": "DELETE"}
    stale = client.post("/web/v1/account/delete", json=body, headers={"authorization": "Bearer test:u1"})
    assert stale.status_code == 401, stale.text
    assert stale.json()["error"]["detail"]["reason"] == "recent_login_required"
    missing = client.post("/web/v1/account/delete", json={"request_id": str(uuid.uuid4())},
                          headers={"authorization": "Bearer test:u1:fresh"})
    assert missing.status_code == 400
    ok = client.post("/web/v1/account/delete", json={**body, "request_id": str(uuid.uuid4())},
                     headers={"authorization": "Bearer test:u1:fresh"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] in ("PROCESSING", "COMPLETED")
    anon = client.post("/web/v1/account/delete", json=body)
    assert anon.status_code == 401, anon.text
