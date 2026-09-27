from __future__ import annotations

import json
import random
from collections import Counter

import pytest

from app.manifests.manifest import ManifestEntry
from app.questions.exposure import ExposureUnion, append_unique
from app.questions.gate import language_gate_report
from app.questions.models import (
    CONCEPT_ID_RE,
    Difficulty,
    OptionText,
    QuestionStatus,
    QuestionTranslation,
    competitive_eligibility,
    validate_competitive_text,
)
from app.questions.seed import SEED_LANGUAGES, load_seed_items, seed_group_id
from app.questions.selector import (
    QUICK_NORMAL_ORDER,
    InsufficientInventory,
    select_quick,
    select_survival,
)
from app.questions.taxonomy import CATEGORIES, CATEGORY_IDS, is_valid_subcategory

# ---------------------------------------------------------------- taxonomy & seed content


def test_exactly_nine_categories_and_no_gaming():
    assert len(CATEGORIES) == 9
    assert "gaming" not in CATEGORY_IDS


def test_every_seed_item_is_competitive_valid_in_both_languages():
    items = load_seed_items()
    assert len(items) == 360
    per_category = Counter(i["category_id"] for i in items)
    assert set(per_category) == set(CATEGORY_IDS) and set(per_category.values()) == {40}
    seen_questions = set()
    for item in items:
        assert is_valid_subcategory(item["category_id"], item["subcategory_id"]), item["key"]
        assert item["global_relevance_score"] >= 4 and item["time_sensitive"] is False
        assert all(CONCEPT_ID_RE.match(o["concept_id"]) for o in item["options"])
        for lang in SEED_LANGUAGES:
            translation = QuestionTranslation(
                question_group_id="g", question_version=1, language=lang, question_text=item["question"][lang],
                options=[OptionText(concept_id=o["concept_id"], text=o[lang]) for o in item["options"]])
            assert validate_competitive_text(translation, item["correct"]) == [], (item["key"], lang)
        assert item["question"]["en"] not in seen_questions
        seen_questions.add(item["question"]["en"])


def test_text_validation_rejects_bad_questions():
    bad = QuestionTranslation(question_group_id="g", question_version=1, language="en", question_text="x" * 161,
                              options=[OptionText(concept_id="a", text="All of the above"),
                                       OptionText(concept_id="b", text="B"),
                                       OptionText(concept_id="b2", text="b")])
    problems = validate_competitive_text(bad, "zzz")
    assert {"question_too_long", "options_not_four", "forbidden_option_pattern", "duplicate_option_text",
            "correct_not_in_options"} <= set(problems)


# ---------------------------------------------------------------- eligibility & manifests


def _group(**overrides):
    base = {"status": "ACTIVE", "verified": True, "competitive_enabled": True, "global_relevance_score": 5,
            "review_after_ms": None, "version": 3, "modes": ["QUICK", "SURVIVAL"]}
    base.update(overrides)
    return base


def _translation(**overrides):
    base = {"translation_verified": True, "competitive_text_valid": True, "question_version": 3}
    base.update(overrides)
    return base


@pytest.mark.parametrize("group_changes,translation_changes,reason", [
    ({"status": "QUARANTINED"}, {}, "not_active"),
    ({"verified": False}, {}, "not_verified"),
    ({"competitive_enabled": False}, {}, "competitive_disabled"),
    ({"global_relevance_score": 3}, {}, "low_global_relevance"),
    ({"review_after_ms": 5}, {}, "review_expired"),
    ({}, {"translation_verified": False}, "translation_unverified"),
    ({}, {"competitive_text_valid": False}, "text_invalid"),
    ({}, {"question_version": 2}, "translation_version_mismatch"),
    ({"media_asset_id": "m1"}, {}, "media_missing"),
])
def test_competitive_eligibility_filters(group_changes, translation_changes, reason):
    assert reason in competitive_eligibility(_group(**group_changes), _translation(**translation_changes), 10)


def test_eligible_question_passes():
    assert competitive_eligibility(_group(), _translation(), 10) == []
    assert "translation_missing" in competitive_eligibility(_group(), None, 10)


async def test_manifests_built_per_language_mode_difficulty_without_answers(container):
    store = container.store
    for lang in SEED_LANGUAGES:
        for mode in ("QUICK", "SURVIVAL"):
            counts = {d: len(await container.manifest_cache.get(lang, mode, d.value)) for d in Difficulty}
            assert counts == {Difficulty.EASY: 126, Difficulty.MEDIUM: 144, Difficulty.HARD: 90}
    blobs = [doc for path, doc in store.dump("pool_manifest_chunks").items()]
    raw = json.dumps(await container.manifest_cache.get("en", "QUICK", "EASY"), default=vars)
    private = next(iter(store.dump("question_private").values()))
    assert private["correct_concept_id"] not in raw.split('"gid"')[0]  # entries hold only metadata
    assert all(set(e.__dict__) == {"qid", "gid", "v", "cat", "sub", "d", "m"}
               for e in await container.manifest_cache.get("en", "QUICK", "EASY"))
    assert blobs


async def test_quarantine_removes_question_from_rebuilt_manifest(container):
    gid = seed_group_id("geography_001")
    await container.question_repo.transition(gid, QuestionStatus.QUARANTINED, "admin", "reported")
    await container.manifest_builder.build_all(["en"])
    for d in Difficulty:
        assert gid not in {e.gid for e in await container.manifest_cache.get("en", "QUICK", d.value)}


def test_invalid_status_transition_rejected():
    from app.questions.models import ALLOWED_TRANSITIONS

    assert QuestionStatus.ACTIVE not in ALLOWED_TRANSITIONS[QuestionStatus.DRAFT]


# ---------------------------------------------------------------- exposure


def test_append_unique_keeps_newest_unique_and_limit():
    assert append_unique([1, 2, 3], [2, 4]) == [1, 3, 2, 4]
    assert append_unique(list(range(10)), [100, 101], limit=5) == [7, 8, 9, 100, 101]


def test_exposure_union_tiers():
    history = tuple(range(3000))
    union = ExposureUnion((history, ()))
    assert union.tier(10) == 0  # older than the last 2500
    assert union.tier(1000) == 1  # in last 2500, not in last 1000
    assert union.tier(2500) == 2  # in last 1000, not in last 300
    assert union.tier(2999) == 3  # in last 300
    assert union.last_seen_rank(2999) > union.last_seen_rank(2800) > union.last_seen_rank(99999)


# ---------------------------------------------------------------- selection


def _pools(n_per_cat: int = 10) -> dict[Difficulty, list[ManifestEntry]]:
    pools: dict[Difficulty, list[ManifestEntry]] = {d: [] for d in Difficulty}
    qid = 0
    for d in Difficulty:
        for cat in CATEGORY_IDS:
            subs = list(next(c for c in CATEGORIES if c.id == cat).subcategories)
            for i in range(n_per_cat):
                qid += 1
                pools[d].append(ManifestEntry(qid, f"g{qid}", 1, cat, subs[i % len(subs)], d.value, False))
    return pools


def test_quick_selection_order_diversity_and_no_repeats():
    pools = _pools()
    for seed in range(30):
        normal, reserves = select_quick(pools, ExposureUnion(((),)), random.Random(seed))
        assert [Difficulty(e.d) for e in normal] == list(QUICK_NORMAL_ORDER)
        assert [e.d for e in reserves] == ["MEDIUM", "HARD", "HARD", "HARD", "HARD"]
        gids = [e.gid for e in normal + reserves]
        assert len(gids) == len(set(gids))
        cats = Counter(e.cat for e in normal)
        assert max(cats.values()) <= 2
        assert len(cats) >= 6
        assert all(a.sub != b.sub for a, b in zip(normal, normal[1:], strict=False))


def test_selection_prefers_unseen_then_falls_back_through_ladder():
    pools = _pools(n_per_cat=2)
    all_qids = [e.qid for entries in pools.values() for e in entries]
    unseen = {e.qid for e in pools[Difficulty.EASY][:4]}
    history = tuple(q for q in all_qids if q not in unseen)
    normal, _ = select_quick(pools, ExposureUnion((history,)), random.Random(1))
    assert {normal[0].qid, normal[1].qid} <= unseen
    # When everything was seen, selection still succeeds by least-recently-seen.
    normal, _ = select_quick(pools, ExposureUnion((tuple(all_qids),)), random.Random(1))
    assert len(normal) == 10


def test_exposure_is_never_weakened_for_diversity():
    pools = _pools(n_per_cat=3)
    # Only geography EASY questions are unseen; diversity must not pull a seen question instead.
    unseen = [e for e in pools[Difficulty.EASY] if e.cat == "geography"]
    history = tuple(e.qid for e in pools[Difficulty.EASY] if e.cat != "geography")
    normal, _ = select_quick(pools, ExposureUnion((history,)), random.Random(3))
    assert normal[0].cat == normal[1].cat == "geography"
    assert {normal[0].gid, normal[1].gid} <= {e.gid for e in unseen}


def test_selection_raises_when_inventory_exhausted():
    pools = _pools(n_per_cat=1)
    pools[Difficulty.HARD] = pools[Difficulty.HARD][:3]
    with pytest.raises(InsufficientInventory):
        select_quick(pools, ExposureUnion(((),)), random.Random(0))


def test_survival_selection_spreads_difficulties():
    picks = select_survival(_pools(), ExposureUnion(((),)), random.Random(0))
    assert {d: len(v) for d, v in picks.items()} == {Difficulty.EASY: 14, Difficulty.MEDIUM: 14, Difficulty.HARD: 12}
    gids = [e.gid for v in picks.values() for e in v]
    assert len(gids) == len(set(gids)) >= 40


# ---------------------------------------------------------------- plans


async def test_quick_plan_is_complete_and_verified(container):
    plan = await container.question_plans.quick_plan("en", ["u1", "u2"], "match-1")
    assert len(plan["normal"]) == 10 and len(plan["reserve"]) == 5
    for item in plan["normal"] + plan["reserve"]:
        assert item["correct"] in {o["concept_id"] for o in item["options"]}
        assert len(item["options"]) == 4 and item["text"]


async def test_plan_skips_question_quarantined_after_manifest_build(container):
    """A quarantine race: manifest still lists the question, but plan verification drops it."""
    first = await container.question_plans.quick_plan("en", ["u1"], "seed-x")
    victim = first["normal"][0]["gid"]
    await container.question_repo.transition(victim, QuestionStatus.QUARANTINED, "admin", "reports")
    second = await container.question_plans.quick_plan("en", ["u1"], "seed-x")
    assert victim not in {i["gid"] for i in second["normal"] + second["reserve"]}


async def test_plan_avoids_recent_human_exposure(container):
    first = await container.question_plans.quick_plan("en", ["u1"], "a")
    await container.exposure.append("u1", [i["qid"] for i in first["normal"]])
    second = await container.question_plans.quick_plan("en", ["u1", "u2"], "a")
    assert not {i["qid"] for i in first["normal"]} & {i["qid"] for i in second["normal"]}


async def test_turkish_plan_uses_verified_turkish_text(container):
    plan = await container.question_plans.quick_plan("tr", ["u1"], "tr-1")
    assert all(item["text"] for item in plan["normal"])


async def test_language_gate_reports_not_ready_for_seed(container):
    report = await language_gate_report(container.manifest_cache, "en", trials=20)
    assert report.total_groups == 360
    assert report.categories_represented == 9
    assert report.soft_launch_ready is False


# ---------------------------------------------------------------- API: categories + Synova (Phase 1 exit)


def test_categories_endpoint_localised(api):
    res = api.get("/v1/categories", "u1", lang="tr")
    assert res.status_code == 200
    names = [c["name"] for c in res.json()["categories"]]
    assert len(names) == 9 and "Coğrafya ve Dünya" in names


def test_synova_serves_shared_question_and_decides_server_side(api, container):
    res = api.post("/v1/synova/questions/next", "solo1", {"language": "en", "category_ids": ["history"]})
    assert res.status_code == 200, res.text
    body = res.json()
    question = body["question"]
    assert question["category_id"] == "history" and len(question["options"]) == 4
    assert "correct" not in json.dumps(body)
    private = container.store.dump("synova_items")[f"synova_items/{body['item_id']}"]
    wrong = next(o["option_id"] for o in question["options"] if o["option_id"] != private["correct"])
    res = api.post(f"/v1/synova/questions/{body['item_id']}/answer", "solo1", {"option_id": wrong})
    assert res.status_code == 200 and res.json()["correct"] is False
    res = api.post(f"/v1/synova/questions/{body['item_id']}/answer", "solo1", {"option_id": wrong})
    assert res.json()["error"]["code"] == "ANSWER_ALREADY_SUBMITTED"
    # Exposure is shared with Live Trivia selection.
    history = container.store.dump("user_recent_questions")["user_recent_questions/solo1"]["qids"]
    assert history == [question["qid"]]
