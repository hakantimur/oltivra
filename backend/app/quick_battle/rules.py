"""Quick Battle rules (spec §3): first authoritatively accepted correct answer wins the question.

Wrong human answer: locked for the round, -4. No answer: 0. Points = clamp(floor((ends - received)/1000), 1, 10).
Top-score ties after question 10 enter Sudden Death (max five unresolved questions).
"""

from __future__ import annotations

import math
from typing import Any

from app.common.keys import Keyring
from app.matches import engine
from app.matches.model import (
    AnswerStatus,
    EventType,
    Phase,
    RoundKind,
    StepResult,
    append_event,
    current_round,
    participants,
)


def points_for(ends_at_ms: int, received_at_ms: int) -> int:
    return max(1, min(10, (ends_at_ms - received_at_ms) // 1000))


def _cfg(state: dict[str, Any]) -> dict[str, Any]:
    return state["config"]["mode"]


def init(state: dict[str, Any]) -> None:
    state["match_phase"] = Phase.QUICK_NORMAL.value
    state["normal_rounds_opened"] = 0
    state["sd_rounds_opened"] = 0


def on_round_opened(state: dict[str, Any]) -> None:
    for p in participants(state).values():
        p["answered_this_round"] = False
    if current_round(state)["kind"] == RoundKind.NORMAL:
        state["normal_rounds_opened"] = int(state.get("normal_rounds_opened", 0)) + 1
    else:
        state["sd_rounds_opened"] = int(state.get("sd_rounds_opened", 0)) + 1


def _not_left(state: dict[str, Any]) -> list[str]:
    return [pid for pid, p in sorted(participants(state).items(), key=lambda kv: kv[1]["slot"]) if not p.get("left")]


def next_round(state: dict[str, Any], keys: Keyring):
    cfg = _cfg(state)
    plan = state["plan"]
    opened = int(state.get("normal_rounds_opened", 0))
    if state["match_phase"] == Phase.QUICK_NORMAL and opened < cfg["normal_questions"]:
        return plan["normal"][opened], RoundKind.NORMAL, cfg["seconds"] * 1000, _not_left(state)
    if state["match_phase"] == Phase.QUICK_NORMAL:
        scores = {pid: p["score"] for pid, p in participants(state).items()}
        top = max(scores.values())
        tied = [pid for pid in _not_left(state) if scores[pid] == top]
        if len(tied) < 2:
            return None
        state["match_phase"] = Phase.QUICK_SUDDEN_DEATH.value
        state["sd_tied"] = tied
        append_event(state, current_round(state).get("closed_at_ms", 0), EventType.SUDDEN_DEATH, value=len(tied))
    if state.get("sd_winner"):
        return None
    eligible = [pid for pid in state.get("sd_tied") or [] if not participants(state)[pid].get("left")]
    if len(eligible) == 1:
        state["sd_winner"] = eligible[0]
        return None
    sd_count = int(state.get("sd_rounds_opened", 0))
    reserves = plan.get("reserve") or []
    if not eligible or sd_count >= cfg["sudden_death_unresolved_cap"] or sd_count >= len(reserves):
        return None
    return reserves[sd_count], RoundKind.SUDDEN_DEATH, cfg["seconds"] * 1000, eligible


def _project_bot_wrongs(state: dict[str, Any], before_ms: int, now_ms: int) -> None:
    """A bot's wrong-answer penalty is projected at resolution (spec §3.3); only attempts made before the
    round closed count."""
    rnd = current_round(state)
    normal = rnd["kind"] == RoundKind.NORMAL
    penalty = _cfg(state)["wrong_penalty"] if normal else 0
    for pid, plan in sorted((state.get("bot_plans") or {}).items(), key=lambda kv: kv[1]["response_at_ms"]):
        if plan.get("round_id") != rnd["round_id"] or not plan.get("will_answer") or plan.get("will_be_correct"):
            continue
        if pid not in (rnd.get("eligible") or []) or plan["response_at_ms"] >= before_ms:
            continue
        if pid in (rnd.get("answers") or {}):
            continue
        answer = {"concept_id": plan["selected_concept_id"], "received_at_ms": plan["response_at_ms"],
                  "correct": False, "request_id": f"bot:{plan['commit_hash'][:12]}", "score_delta": penalty}
        rnd["answers"] = {**(rnd.get("answers") or {}), pid: answer}
        bot = participants(state)[pid]
        bot["score"] += penalty
        bot["answered_this_round"] = True
        append_event(state, now_ms, EventType.WRONG, pid, penalty)


def _award_win(state: dict[str, Any], pid: str, received_at_ms: int, now_ms: int) -> int:
    rnd = current_round(state)
    participant = participants(state)[pid]
    points = points_for(rnd["ends_at_ms"], received_at_ms)
    rnd["winner_pid"] = pid
    if rnd["kind"] == RoundKind.NORMAL:
        participant["score"] += points
        participant["wins"] = int(participant.get("wins", 0)) + 1
        participant["win_ms_sum"] = int(participant.get("win_ms_sum", 0)) + (received_at_ms - rnd["starts_at_ms"])
        rnd["points"] = points
        append_event(state, now_ms, EventType.WIN, pid, points)
    else:
        state["sd_winner"] = pid
        rnd["points"] = 0
        append_event(state, now_ms, EventType.WIN, pid, 0)
    participant["correct_rounds"] = int(participant.get("correct_rounds", 0)) + 1
    participant["correct_ms_sum"] = int(participant.get("correct_ms_sum", 0)) + (received_at_ms - rnd["starts_at_ms"])
    return points


def apply_due_bot_winner(state: dict[str, Any], due_ms: int, now_ms: int, result: StepResult, source: str) -> bool:
    earliest = engine._earliest_correct_bot(state)
    if earliest is None or earliest[1] > due_ms:
        return False
    pid, response_at = earliest
    rnd = current_round(state)
    _project_bot_wrongs(state, response_at, now_ms)
    plan = state["bot_plans"][pid]
    points = points_for(rnd["ends_at_ms"], response_at)
    rnd["answers"] = {**(rnd.get("answers") or {}), pid: {
        "concept_id": plan["selected_concept_id"], "received_at_ms": response_at, "correct": True,
        "request_id": f"bot:{plan['commit_hash'][:12]}",
        "score_delta": points if rnd["kind"] == RoundKind.NORMAL else 0}}
    participants(state)[pid]["answered_this_round"] = True
    _award_win(state, pid, response_at, now_ms)
    engine.close_round(state, now_ms, result, source, _cfg(state)["reveal_ms"])
    return True


def expire_round(state: dict[str, Any], ends_at_ms: int, now_ms: int, result: StepResult, source: str) -> None:
    _project_bot_wrongs(state, ends_at_ms, now_ms)
    append_event(state, now_ms, EventType.NO_WINNER)
    engine.close_round(state, now_ms, result, source, _cfg(state)["reveal_ms"])


def on_answer(state: dict[str, Any], pid: str, answer: dict[str, Any], received_at_ms: int, result: StepResult,
              source: str) -> None:
    rnd = current_round(state)
    participant = participants(state)[pid]
    if answer["correct"]:
        _project_bot_wrongs(state, received_at_ms, received_at_ms)
        points = _award_win(state, pid, received_at_ms, received_at_ms)
        answer["score_delta"] = points if rnd["kind"] == RoundKind.NORMAL else 0
        rnd["answers"][pid] = answer
        engine.close_round(state, received_at_ms, result, source, _cfg(state)["reveal_ms"])
        return
    penalty = _cfg(state)["wrong_penalty"] if rnd["kind"] == RoundKind.NORMAL else 0
    participant["score"] += penalty
    answer["score_delta"] = penalty
    rnd["answers"][pid] = answer
    append_event(state, received_at_ms, EventType.WRONG, pid, penalty)
    from app.matches.model import bump

    bump(state, received_at_ms, "WRONG_ANSWER", source)


def on_leave(state: dict[str, Any], pid: str, now_ms: int, result: StepResult) -> None:
    participants(state)[pid]["active"] = False


def _ranking_key(state: dict[str, Any], keys_hmac: dict[str, str], pid: str) -> tuple:
    p = participants(state)[pid]
    wins = int(p.get("wins", 0))
    mean_win = (p.get("win_ms_sum", 0) / wins) if wins else math.inf
    return (bool(p.get("left")), -p["score"], -wins, mean_win, keys_hmac[pid])


def final_standings(state: dict[str, Any]) -> dict[str, Any]:
    tiebreak = state["tiebreak_hmac"]
    ordered = sorted(participants(state), key=lambda pid: _ranking_key(state, tiebreak, pid))
    winner = state.get("sd_winner")
    if winner:
        ordered.remove(winner)
        ordered.insert(0, winner)
    placements = {pid: index + 1 for index, pid in enumerate(ordered)}
    return {
        "order": ordered,
        "placements": placements,
        "scores": {pid: participants(state)[pid]["score"] for pid in ordered},
        "wins": {pid: int(participants(state)[pid].get("wins", 0)) for pid in ordered},
        "sudden_death": {"tied": state.get("sd_tied") or [], "rounds": int(state.get("sd_rounds_opened", 0)),
                         "winner": winner},
    }


def public_extras(state: dict[str, Any]) -> dict[str, Any]:
    extras: dict[str, Any] = {"total_normal_rounds": _cfg(state)["normal_questions"]}
    if state.get("match_phase") == Phase.QUICK_SUDDEN_DEATH:
        extras["sudden_death"] = {"tied_pids": state.get("sd_tied") or [],
                                  "question_number": int(state.get("sd_rounds_opened", 0))}
    return extras


def display_round_number(state: dict[str, Any]) -> int:
    if current_round(state).get("kind") == RoundKind.SUDDEN_DEATH:
        return int(state.get("sd_rounds_opened", 0))
    return int(state.get("normal_rounds_opened", 0))


def reveal_payload(state: dict[str, Any]) -> dict[str, Any]:
    rnd = current_round(state)
    text = next(o["text"] for o in rnd["options"] if o["concept_id"] == rnd["correct"])
    payload: dict[str, Any] = {"concept_id": rnd["correct"], "text": text}
    if rnd.get("winner_pid"):
        payload["winner_pid"] = rnd["winner_pid"]
        payload["points"] = rnd.get("points", 0)
    return payload


def public_result(state: dict[str, Any]) -> dict[str, Any]:
    result = state["result"]
    return {"standings": [{"pid": pid, "place": result["placements"][pid], "score": result["scores"][pid],
                           "wins": result["wins"][pid]} for pid in result["order"]],
            "sudden_death_winner_pid": result["sudden_death"].get("winner")}


def own_answer_status(state: dict[str, Any], pid: str, answer: dict[str, Any] | None, eligible: bool) -> AnswerStatus:
    if answer is None:
        return AnswerStatus.NOT_ANSWERED if eligible else AnswerStatus.INELIGIBLE
    return AnswerStatus.ANSWERED_CORRECT if answer["correct"] else AnswerStatus.ANSWERED_WRONG
