"""Survival state machine (spec §4, §40.3): every unresolved edge case ends deterministically."""

from __future__ import annotations

from typing import Any

from app.common.server_config import GameConfig
from app.matches import engine
from app.matches.model import Mode
from app.survival import rules
from tests.engine_helpers import KEYS, answer, new_match, start_round


def survival(humans: int = 4, bots: int = 0, bot_profile: dict | None = None) -> dict[str, Any]:
    state, _ = new_match(Mode.SURVIVAL, humans=humans, bots=bots, bot_profile=bot_profile)
    return state


def resolve(state: dict[str, Any]) -> engine.StepResult:
    return engine.resolve_due(state, KEYS, state["round"]["ends_at_ms"] + engine.GRACE_MS, "TEST")


def advance(state: dict[str, Any]) -> engine.StepResult:
    return engine.resolve_due(state, KEYS, state["round"]["reveal_ends_at_ms"], "TEST")


def status(state: dict[str, Any], i: int) -> str:
    return state["participants"][f"ph{i}"]["survival_status"]


def play(state: dict[str, Any], correct: list[int] = (), wrong: list[int] = (), offsets: dict[int, int] | None = None):
    start = start_round(state)
    offsets = offsets or {}
    for i in correct:
        assert answer(state, f"u{i}", True, start + offsets.get(i, 1000)).outcome["accepted"]
    for i in wrong:
        assert answer(state, f"u{i}", False, start + offsets.get(i, 1500)).outcome["accepted"]
    resolve(state)
    assert state["state"] in ("ROUND_RESOLVE", "FINISHED_PENDING_SETTLEMENT")


def test_correctness_hidden_while_active():
    state = survival()
    start = start_round(state)
    outcome = answer(state, "u0", False, start + 800).outcome
    assert outcome["locked"] is True and "correct" not in outcome
    root = engine.project(state, KEYS)
    public = root["public"]
    assert public["participants"]["ph0"]["answer_locked"] is True
    assert all(p["survival_status"] == "ACTIVE" for p in public["participants"].values())
    assert "correct_answer_reveal" not in public and "round_outcome" not in public
    assert root["player_private"]["u0"]["own_answer_status"] == "LOCKED"


def test_normal_elimination_and_survivors_continue():
    state = survival()
    play(state, correct=[0, 1], wrong=[2])
    assert [status(state, i) for i in range(4)] == ["SURVIVED", "SURVIVED", "ELIMINATED", "ELIMINATED"]
    public = engine.project(state, KEYS)["public"]
    assert public["correct_answer_reveal"]["eliminated"] == ["ph2", "ph3"]
    assert public["round_outcome"]["resolution"] == "NORMAL"
    advance(state)
    assert state["round"]["eligible"] == ["ph0", "ph1"]
    assert status(state, 0) == "ACTIVE"
    # An eliminated player is a spectator: no option order, cannot answer.
    private = engine.project(state, KEYS)["player_private"]["u2"]
    assert private["own_answer_status"] == "INELIGIBLE" and "option_order" not in private
    start_round(state)
    assert answer(state, "u2", True, state["round"]["starts_at_ms"] + 500).outcome["error"] == "FORBIDDEN"


def test_single_correct_survivor_wins_immediately():
    state = survival(humans=3)
    play(state, correct=[1], wrong=[0])
    assert state["winner_pid"] == "ph1"
    advance(state)
    assert state["state"] == "FINISHED_PENDING_SETTLEMENT"
    result = state["result"]
    assert result["placements"] == {"ph1": 1, "ph0": 2, "ph2": 2}  # one elimination round = one band


def test_all_submitted_wrong_protects_and_rescues_one_band_lower():
    state = survival()
    difficulty = None
    start_round(state)
    difficulty = state["round"]["difficulty"]
    start = state["round"]["starts_at_ms"]
    answer(state, "u0", False, start + 900)
    answer(state, "u1", False, start + 1200)
    resolve(state)
    assert [status(state, i) for i in range(4)] == ["PROTECTED", "PROTECTED", "ELIMINATED", "ELIMINATED"]
    assert state["unresolved_round_streak"] == 1
    advance(state)
    rnd = state["round"]
    assert rnd["kind"] == "RESCUE"
    assert rnd["difficulty"] == {"HARD": "MEDIUM", "MEDIUM": "EASY", "EASY": "EASY"}[difficulty]
    assert rnd["duration_ms"] == 15_000 and state["match_phase"] == "SURVIVAL_RESCUE"
    assert rnd["gid"] not in state["used_gids"][:-1]  # fresh question group


def test_all_wrong_with_one_remaining_player_wins():
    state = survival(humans=3)
    play(state, wrong=[0])
    assert state["winner_pid"] == "ph0"
    advance(state)
    assert state["state"] == "FINISHED_PENDING_SETTLEMENT"


def test_last_two_both_wrong_are_protected():
    state = survival(humans=2)
    play(state, wrong=[0, 1])
    assert status(state, 0) == status(state, 1) == "PROTECTED"
    advance(state)
    assert state["round"]["kind"] == "RESCUE" and state["round"]["eligible"] == ["ph0", "ph1"]


def test_nobody_answers_starts_easy_fifteen_second_rescue():
    state = survival()
    play(state)
    assert all(status(state, i) == "PROTECTED" for i in range(4))
    advance(state)
    rnd = state["round"]
    assert rnd["kind"] == "RESCUE" and rnd["difficulty"] == "EASY" and rnd["duration_ms"] == 20_000
    assert len(rnd["eligible"]) == 4


def test_rescue_success_resets_streak():
    state = survival()
    play(state)
    advance(state)
    play(state, correct=[0, 2])
    assert state["unresolved_round_streak"] == 0
    advance(state)
    assert state["round"]["kind"] == "NORMAL"


def test_three_unresolved_rounds_trigger_final_tiebreak_then_deterministic_order():
    state = survival()
    play(state, correct=[0, 1, 2], offsets={0: 1000, 1: 500, 2: 2000})
    advance(state)
    for _ in range(3):
        play(state)
        advance(state)
    rnd = state["round"]
    assert rnd["kind"] == "TIEBREAK" and rnd["difficulty"] == "EASY" and rnd["duration_ms"] == 20_000
    assert state["tiebreak_start_active"] == ["ph0", "ph1", "ph2"]
    play(state)  # nobody answers the final tiebreak: all eliminated, deterministic ordering decides
    assert state["deterministic_order"] == ["ph1", "ph0", "ph2"]
    assert state["winner_pid"] == "ph1"
    advance(state)
    assert state["state"] == "FINISHED_PENDING_SETTLEMENT"
    assert state["result"]["placements"] == {"ph1": 1, "ph0": 2, "ph2": 3, "ph3": 4}


def test_tiebreak_unique_correct_answer_wins():
    state = survival(humans=3)
    for _ in range(3):
        play(state)
        advance(state)
    assert state["round"]["kind"] == "TIEBREAK"
    play(state, correct=[2], wrong=[0])
    assert state["winner_pid"] == "ph2" and not state.get("deterministic_order")
    advance(state)
    assert state["result"]["placements"]["ph2"] == 1


def test_tiebreak_multiple_correct_ordered_deterministically():
    state = survival(humans=3)
    for _ in range(3):
        play(state)
        advance(state)
    play(state, correct=[0, 1], offsets={0: 3000, 1: 1000})
    assert state["deterministic_order"] == ["ph1", "ph0"]
    advance(state)
    assert state["result"]["placements"] == {"ph1": 1, "ph0": 2, "ph2": 3}


def test_placement_bands_latest_elimination_ranks_higher():
    state = survival(humans=6)
    play(state, correct=[0, 1, 2, 3], wrong=[4])  # ph4, ph5 out in round 1
    advance(state)
    play(state, correct=[0], wrong=[1, 2])  # ph1, ph2, ph3 out in round 2, ph0 wins
    advance(state)
    placements = state["result"]["placements"]
    assert placements == {"ph0": 1, "ph1": 2, "ph2": 2, "ph3": 2, "ph4": 5, "ph5": 5}


def test_leave_eliminates_and_last_survivor_wins():
    state = survival(humans=2)
    start_round(state)
    result = engine.apply_leave(state, KEYS, "u1", state["round"]["starts_at_ms"] + 100)
    assert result.outcome["left"] is True
    assert state["winner_pid"] == "ph0"
    assert state["state"] == "FINISHED_PENDING_SETTLEMENT"
    assert state["result"]["placements"] == {"ph0": 1, "ph1": 2}


def test_disconnected_player_eliminated_by_no_answer():
    state = survival(humans=3)
    play(state, correct=[0, 1])  # u2 is offline
    assert status(state, 2) == "ELIMINATED"


def test_bots_play_hidden_and_match_always_terminates():
    profile = GameConfig().bots.profiles["NORMAL"].model_dump()
    for seed in range(5):
        state, _ = new_match(Mode.SURVIVAL, humans=1, bots=9, bot_profile=profile)
        state["match_id"] = f"m-bots-{seed}"
        for _ in range(60):
            if state["state"] == "FINISHED_PENDING_SETTLEMENT":
                break
            start_round(state)
            resolve(state)
            advance(state)
        assert state["state"] == "FINISHED_PENDING_SETTLEMENT"
        placements = state["result"]["placements"]
        assert sorted(placements.values())[0] == 1 and list(placements.values()).count(1) == 1


def test_bot_locks_appear_without_revealing_correctness():
    profile = GameConfig().bots.profiles["EXPERT"].model_dump()
    state = survival(humans=1, bots=3, bot_profile=profile)
    start = start_round(state)
    late = max(p["response_at_ms"] for p in state["bot_plans"].values())
    answer(state, "u0", True, min(late + 1, start + 10_800))
    public = engine.project(state, KEYS)["public"]
    answering = [pid for pid, plan in state["bot_plans"].items() if plan["will_answer"]]
    assert all(public["participants"][pid]["answer_locked"] for pid in answering)
    assert all(p["survival_status"] == "ACTIVE" for p in public["participants"].values())


def test_refill_requested_when_reserve_low_and_applied_once():
    config = GameConfig()
    from tests.engine_helpers import roster
    from tests.engine_helpers import survival_plan as plan_builder

    state, result = engine.create_match_state(
        keys=KEYS, match_id="m-refill", shard_id="live-00", mode=Mode.SURVIVAL, language="en",
        region="europe-west1", roster=roster(4, 0), plan=plan_builder(per=3),
        config_snapshot=config.match_snapshot("SURVIVAL"), bot_profiles={}, reaction_ids=[],
        ranked={"eligible": True}, source="TEST", now_ms=1)
    refill = [e for e in result.effects if e.kind == "REFILL_QUESTIONS"]
    assert refill and refill[0].data == {"batch": 1}
    assert state["refill_pending"] is True
    extra = {"EASY": [dict(state["plan"]["pools"]["EASY"][0]), {**state["plan"]["pools"]["EASY"][0], "gid": "gx"}]}
    rules.add_pool_items(state, 1, extra, 2)
    assert rules.pool_remaining(state) == 8 + 1  # duplicate gid ignored, one fresh item added
    assert state["refill_pending"] is False
    before = rules.pool_remaining(state)
    rules.add_pool_items(state, 1, {"EASY": [{**extra["EASY"][1], "gid": "gy"}]}, 3)  # stale batch
    assert rules.pool_remaining(state) == before


def test_survival_opens_with_easy_rounds_whatever_the_count():
    for humans in (2, 6, 10):
        assert survival(humans=humans)["round"]["difficulty"] == "EASY"


def test_survival_difficulty_follows_active_count_after_the_opening():
    state = survival(humans=4)
    state["round_index"] = 5
    assert rules._normal_difficulty(state, KEYS, 2) == "HARD"
    assert rules._normal_difficulty(state, KEYS, 3) in ("MEDIUM", "HARD")
    assert rules._normal_difficulty(state, KEYS, 6) in ("EASY", "MEDIUM")
    assert rules._normal_difficulty(state, KEYS, 9) in ("EASY", "MEDIUM")
    state["round_index"] = 1  # rounds 1-3 are the EASY opening
    assert rules._normal_difficulty(state, KEYS, 2) == "EASY"
