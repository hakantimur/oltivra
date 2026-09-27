"""Quick Battle engine: spec §3, §20, §22, §40.1, §40.2, §40.5."""

from __future__ import annotations

import copy

import pytest

from app.common.server_config import GameConfig
from app.matches import engine
from app.matches.model import MatchState, Mode, Phase
from app.quick_battle.rules import points_for
from tests.engine_helpers import (
    KEYS,
    advance,
    answer,
    finish_round_without_answers,
    new_match,
    start_round,
)


@pytest.mark.parametrize("remaining_ms,points", [
    (10_999, 10), (10_000, 10), (9_999, 9), (8_300, 8), (1_200, 1), (1_001, 1), (100, 1),
])
def test_scoring_boundaries(remaining_ms, points):
    assert points_for(100_000, 100_000 - remaining_ms) == points


def test_round_loading_publishes_only_current_question_with_two_second_lead():
    state, result = new_match()
    assert state["state"] == MatchState.ROUND_LOADING
    rnd = state["round"]
    assert rnd["starts_at_ms"] - state["created_at_ms"] == 2000
    assert rnd["ends_at_ms"] - rnd["starts_at_ms"] == 11_000
    kinds = {e.kind for e in result.effects}
    assert {"ROUND_START", "ROUND_RECOVERY"} <= kinds
    root = engine.project(state, KEYS)
    public_blob = str(root["public"])
    assert "Question 1?" in public_blob and "Question 2?" not in public_blob
    assert "correct" not in root["public"].get("current_question", {})
    assert root["public"].get("correct_answer_reveal") is None
    # Every player gets an independent order of the same four concepts; others' orders are not public.
    orders = [root["player_private"][f"u{i}"]["option_order"] for i in range(4)]
    assert all(sorted(o.values()) == sorted(orders[0].values()) for o in orders)
    assert "option_order" not in public_blob


def test_first_correct_answer_wins_and_closes_round():
    state, _ = new_match()
    starts = start_round(state)
    result = answer(state, "u1", True, starts + 2_500)
    assert result.outcome["accepted"] and result.outcome["correct"] and result.outcome["score_delta"] == 8
    assert state["state"] == MatchState.ROUND_REVEAL
    late = answer(state, "u2", True, starts + 2_600)
    assert late.outcome["error"] == "ROUND_NOT_ACTIVE"
    public = engine.project(state, KEYS)["public"]
    assert public["correct_answer_reveal"]["winner_pid"] == "ph1"
    assert public["participants"]["ph1"]["score"] == 8
    assert [e["type"] for e in public["events"]][-1] == "WIN"


def test_wrong_answer_locks_player_minus_four_and_round_continues():
    state, _ = new_match()
    starts = start_round(state)
    wrong = answer(state, "u0", False, starts + 1_000)
    assert wrong.outcome["score_delta"] == -4 and state["state"] == MatchState.ROUND_ACTIVE
    again = answer(state, "u0", True, starts + 1_500, request_id="another")
    assert again.outcome["error"] == "ANSWER_ALREADY_SUBMITTED"
    public = engine.project(state, KEYS)["public"]
    assert public["participants"]["ph0"]["score"] == -4
    assert public["participants"]["ph0"]["answer_locked"] is True
    event = public["events"][-1]
    assert event["type"] == "WRONG" and event["value"] == -4
    assert "concept" not in str(event)  # the selected wrong option is never public


def test_duplicate_request_returns_original_outcome():
    state, _ = new_match()
    starts = start_round(state)
    first = answer(state, "u0", False, starts + 1_000, request_id="same")
    replay = answer(state, "u0", False, starts + 1_200, request_id="same")
    assert replay.outcome["replay"] is True and replay.outcome["score_delta"] == first.outcome["score_delta"]
    assert state["participants"]["ph0"]["score"] == -4
    reused = answer(state, "u0", True, starts + 1_300, request_id="same")  # same key, different option
    assert reused.outcome["error"] == "IDEMPOTENCY_KEY_REUSED" and state["participants"]["ph0"]["score"] == -4


def test_late_and_invalid_answers_rejected():
    state, _ = new_match()
    starts = start_round(state)
    rnd = state["round"]
    bad = engine.apply_answer(state, KEYS, uid="u0", round_id=rnd["round_id"], option_id="not-an-option",
                              received_at_ms=starts + 100, request_id="x")
    assert bad.outcome["error"] == "INVALID_OPTION"
    late = answer(state, "u1", True, rnd["ends_at_ms"])
    assert late.outcome["error"] == "ROUND_EXPIRED"
    assert state["state"] == MatchState.ROUND_REVEAL  # the reconciliation was still committed
    stranger = engine.apply_answer(state, KEYS, uid="nobody", round_id=rnd["round_id"], option_id="c1_a",
                                   received_at_ms=starts, request_id="y")
    assert stranger.outcome["error"] == "NOT_MATCH_PARTICIPANT"


def test_answer_before_round_start_rejected():
    state, _ = new_match()
    early = answer(state, "u0", True, state["round"]["starts_at_ms"] - 1)
    assert early.outcome["error"] == "ROUND_NOT_ACTIVE"


def test_no_answer_scores_zero_and_nobody_correct_reveals():
    state, _ = new_match()
    start_round(state)
    ends = state["round"]["ends_at_ms"]
    engine.resolve_due(state, KEYS, ends, "TASK")  # inside grace window: not yet closed
    assert state["state"] == MatchState.ROUND_ACTIVE
    engine.resolve_due(state, KEYS, ends + engine.GRACE_MS, "TASK")
    assert state["state"] == MatchState.ROUND_REVEAL
    assert all(p["score"] == 0 for p in state["participants"].values())
    assert engine.project(state, KEYS)["public"]["correct_answer_reveal"].get("winner_pid") is None


def test_timely_answer_in_flight_during_grace_is_accepted():
    state, _ = new_match()
    start_round(state)
    ends = state["round"]["ends_at_ms"]
    engine.resolve_due(state, KEYS, ends + 100, "SYNC")
    result = answer(state, "u2", True, ends - 5)
    assert result.outcome["accepted"] and result.outcome["score_delta"] == 1


def test_multiple_wrong_then_correct():
    state, _ = new_match()
    starts = start_round(state)
    answer(state, "u0", False, starts + 500)
    answer(state, "u1", False, starts + 700)
    res = answer(state, "u2", True, starts + 3_000)
    assert res.outcome["score_delta"] == 8
    scores = {pid: p["score"] for pid, p in state["participants"].items()}
    assert scores == {"ph0": -4, "ph1": -4, "ph2": 8, "ph3": 0}


def test_concurrent_correct_answers_yield_one_winner():
    """Two correct answers race; whichever transaction commits first wins, the other is rejected."""
    state, _ = new_match()
    starts = start_round(state)
    a = answer(state, "u3", True, starts + 4_000)
    b = answer(state, "u1", True, starts + 3_900)  # received earlier but committed later
    assert a.outcome["accepted"] and b.outcome["error"] == "ROUND_NOT_ACTIVE"
    assert sum(1 for p in state["participants"].values() if p["wins"]) == 1


def _winning_bot_profile():
    profile = GameConfig().bots.profiles["EXPERT"].model_dump()
    profile.update(answer_rate=1.0, accuracy={"EASY": 1.0, "MEDIUM": 1.0, "HARD": 1.0})
    return profile


def test_due_bot_winner_beats_later_human_and_uses_planned_time():
    state, result = new_match(humans=1, bots=3, bot_profile=_winning_bot_profile())
    assert any(e.kind == "BOT_WINNER" for e in result.effects)
    starts = start_round(state)
    plans = state["bot_plans"]
    first_pid, first_plan = min(plans.items(), key=lambda kv: kv[1]["response_at_ms"])
    human = answer(state, "u0", True, first_plan["response_at_ms"] + 1)
    assert human.outcome["error"] == "ROUND_NOT_ACTIVE"
    assert state["round"]["winner_pid"] == first_pid
    assert state["participants"][first_pid]["score"] == points_for(state["round"]["ends_at_ms"],
                                                                   first_plan["response_at_ms"])
    assert starts < first_plan["response_at_ms"]


def test_human_received_before_bot_time_wins_even_if_committed_later():
    state, _ = new_match(humans=1, bots=3, bot_profile=_winning_bot_profile())
    start_round(state)
    earliest = min(p["response_at_ms"] for p in state["bot_plans"].values())
    engine.resolve_due(state, KEYS, earliest + 100, "BOT_WINNER")  # inside grace: bot not yet applied
    res = answer(state, "u0", True, earliest - 1)
    assert res.outcome["accepted"] and state["round"]["winner_pid"] == "ph0"


def test_duplicate_and_delayed_tasks_are_harmless():
    state, _ = new_match()
    start_round(state)
    ends = state["round"]["ends_at_ms"]
    engine.resolve_due(state, KEYS, ends + 1_000, "TASK")
    snapshot = copy.deepcopy(state)
    engine.resolve_due(state, KEYS, ends + 1_000, "TASK")  # duplicate delivery
    assert state == snapshot
    advance(state)
    round2 = state["round"]["round_id"]
    stale = engine.resolve_due(state, KEYS, ends + 1_500, "TASK")  # delayed old task for round 1
    assert not stale.changed and state["round"]["round_id"] == round2


def test_bot_plan_is_immutable_regardless_of_human_events():
    a, _ = new_match(humans=1, bots=3, bot_profile=_winning_bot_profile())
    b, _ = new_match(humans=1, bots=3, bot_profile=_winning_bot_profile())
    start_round(b)
    answer(b, "u0", False, b["round"]["starts_at_ms"] + 100)
    assert {k: v["commit_hash"] for k, v in a["bot_plans"].items()} == \
        {k: v["commit_hash"] for k, v in b["bot_plans"].items()}


def test_ten_rounds_then_finish_without_tie():
    state, _ = new_match()
    for n in range(10):
        starts = start_round(state)
        assert engine.project(state, KEYS)["public"]["round_number"] == n + 1
        answer(state, "u0", True, starts + 1_000)
        result = advance(state)
    assert state["state"] == MatchState.FINISHED_PENDING_SETTLEMENT
    assert any(e.kind == "START_SETTLEMENT" for e in result.effects)
    standings = state["result"]
    assert standings["order"][0] == "ph0" and standings["placements"]["ph0"] == 1
    assert state["shown_qids"] == list(range(1, 11))


def test_top_score_tie_enters_sudden_death_and_winner_takes_first():
    state, _ = new_match()
    for n in range(10):
        starts = start_round(state)
        uid = "u0" if n % 2 == 0 else "u1"
        answer(state, uid, True, starts + 1_000)  # both reach 50 points
        advance(state)
    assert state["match_phase"] == Phase.QUICK_SUDDEN_DEATH
    assert state["round"]["difficulty"] == "MEDIUM" and state["round"]["eligible"] == ["ph0", "ph1"]
    starts = start_round(state)
    spectator = answer(state, "u2", True, starts + 500)
    assert spectator.outcome["error"] == "FORBIDDEN"
    answer(state, "u0", False, starts + 600)  # wrong in SD: locked, no score change
    assert state["participants"]["ph0"]["score"] == 50
    answer(state, "u1", True, starts + 900)
    advance(state)
    assert state["state"] == MatchState.FINISHED_PENDING_SETTLEMENT
    assert state["result"]["order"][:2] == ["ph1", "ph0"]
    assert state["participants"]["ph1"]["score"] == 50  # SD never alters normal score


def test_sudden_death_unresolved_cap_uses_secondary_rules():
    state, _ = new_match()
    for n in range(10):
        starts = start_round(state)
        if n == 0:
            answer(state, "u0", True, starts + 1_000)  # 10 pts, 1 win, fast
        elif n == 1:
            answer(state, "u1", True, starts + 1_000)  # 10 pts
        else:
            finish_round_without_answers(state)
            continue
        advance(state)
    difficulties = []
    while state["state"] != MatchState.FINISHED_PENDING_SETTLEMENT:
        difficulties.append(state["round"]["difficulty"])
        start_round(state)
        finish_round_without_answers(state)
    assert difficulties == ["MEDIUM", "HARD", "HARD", "HARD", "HARD"]
    order = state["result"]["order"]
    assert set(order[:2]) == {"ph0", "ph1"}
    assert state["result"]["sudden_death"]["winner"] is None


@pytest.mark.parametrize("tied", [3, 4])
def test_three_and_four_player_sudden_death(tied):
    state, _ = new_match()
    for n in range(10):
        starts = start_round(state)
        if n < tied:
            answer(state, f"u{n}", True, starts + 1_000)
            advance(state)
        else:
            finish_round_without_answers(state)
    assert sorted(state["sd_tied"]) == sorted(f"ph{i}" for i in range(tied))


def test_voluntary_leave_ranks_last_and_match_continues():
    state, _ = new_match()
    starts = start_round(state)
    answer(state, "u0", True, starts + 500)
    engine.apply_leave(state, KEYS, "u0", starts + 600)
    advance(state)
    starts = start_round(state)
    assert answer(state, "u0", True, starts + 100).outcome["error"] == "FORBIDDEN"
    for _ in range(9):
        finish_round_without_answers(state)
        if state["state"] == MatchState.FINISHED_PENDING_SETTLEMENT:
            break
        start_round(state)
    assert state["result"]["order"][-1] == "ph0"


def test_all_humans_leaving_finishes_match():
    state, _ = new_match(humans=1, bots=3)
    start_round(state)
    result = engine.apply_leave(state, KEYS, "u0", state["round"]["starts_at_ms"] + 10)
    assert state["state"] == MatchState.FINISHED_PENDING_SETTLEMENT
    assert any(e.kind == "START_SETTLEMENT" for e in result.effects)


def test_bots_never_distinguishable_in_client_payloads():
    state, _ = new_match(humans=1, bots=3)
    root = engine.project(state, KEYS)
    blob = str(root["public"]) + str(root["player_private"])
    assert "bot" not in blob.lower().replace("bot_name", "")
    assert "is_bot" not in blob and "bot_plans" not in blob
    assert set(root["access"]) == {"u0"}


def test_designated_resolver_is_a_non_left_human():
    state, _ = new_match(humans=2, bots=2)
    resolver = engine.project(state, KEYS)["public"]["designated_resolver_pid"]
    assert resolver in {"ph0", "ph1"}
    engine.apply_leave(state, KEYS, state["participants"][resolver]["uid"], state["round"]["starts_at_ms"])
    assert engine.project(state, KEYS)["public"]["designated_resolver_pid"] != resolver


def test_mode_is_quick():
    state, _ = new_match()
    assert state["mode"] == Mode.QUICK


def _media_match(mode: Mode = Mode.QUICK):
    from tests.engine_helpers import T0, item, quick_plan, roster, survival_plan

    plan = quick_plan() if mode == Mode.QUICK else survival_plan()
    media = {"path": "questions/g1/v1/main.webp", "aspect": 1.5,
             "attribution": "Jane Doe / Wikimedia Commons, CC BY 4.0"}
    if mode == Mode.QUICK:
        plan["normal"][0] = {**plan["normal"][0], "media": media}
    else:
        for n, band in enumerate(("EASY", "MEDIUM", "HARD")):
            plan["pools"][band] = [{**item(900 + n, band), "media": media}, *plan["pools"][band]]
    return engine.create_match_state(
        keys=KEYS, match_id="m-media", shard_id="live-00", mode=mode, language="en", region="europe-west1",
        roster=roster(4, 0), plan=plan, config_snapshot=GameConfig().match_snapshot(mode.value), bot_profiles={},
        reaction_ids=[], ranked={"eligible": False, "reason": "test", "human_slots": 4, "bot_slots": 0},
        source="TEST", now_ms=T0)


@pytest.mark.parametrize("mode", [Mode.QUICK, Mode.SURVIVAL])
def test_media_question_without_signed_image_is_replaced_before_answerable(mode):
    state, result = _media_match(mode)
    rnd = state["round"]
    assert rnd["media"] and any(e.kind == "SIGN_MEDIA" for e in result.effects)
    failed_qid, failed_round = rnd["qid"], rnd["round_id"]
    engine.resolve_due(state, KEYS, rnd["starts_at_ms"], "TEST")  # signing never arrived
    new = state["round"]
    assert state["state"] == MatchState.ROUND_LOADING and new["media"] is None
    assert new["qid"] != failed_qid and new["round_id"] != failed_round and new["index"] == 1
    assert new["starts_at_ms"] > rnd["starts_at_ms"]
    engine.resolve_due(state, KEYS, new["starts_at_ms"], "TEST")
    assert state["state"] == MatchState.ROUND_ACTIVE
    if mode == Mode.QUICK:
        assert state["normal_rounds_opened"] == 1 and state["plan"]["normal"][0]["qid"] == new["qid"]
        assert len(state["plan"]["reserve"]) == 4


def test_media_question_with_signed_image_plays_normally():
    state, _ = _media_match()
    rnd = state["round"]
    engine.attach_media(state, rnd["round_id"], "https://signed", rnd["ends_at_ms"] + 30_000, rnd["starts_at_ms"] - 500)
    engine.resolve_due(state, KEYS, rnd["starts_at_ms"], "TEST")
    assert state["state"] == MatchState.ROUND_ACTIVE and state["round"]["qid"] == rnd["qid"]
    question = engine.project(state, KEYS)["public"]["current_question"]
    assert question["signed_image_url"] == "https://signed"
    assert question["image_attribution"] == "Jane Doe / Wikimedia Commons, CC BY 4.0"
