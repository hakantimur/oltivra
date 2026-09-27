"""Survival rules (spec §4, §24.2): hidden correctness, elimination, rescue/tiebreak, deterministic endings.

Correctness stays hidden until ROUND_RESOLVE. Wrong or missing answers eliminate, except for the all-wrong
protection and zero-answer rescue rules; three consecutive unresolved rounds trigger one final Easy tiebreak
whose failure is resolved deterministically, so one winner always exists.
"""

from __future__ import annotations

import random
from typing import Any

from app.common.keys import Keyring
from app.matches import engine
from app.matches.model import (
    AnswerStatus,
    Effect,
    EventType,
    MatchState,
    Phase,
    RoundKind,
    StepResult,
    SurvivalStatus,
    append_event,
    audit,
    bump,
    current_round,
    participants,
)

DIFFICULTIES = ("EASY", "MEDIUM", "HARD")
_FALLBACK = {"EASY": ("EASY", "MEDIUM", "HARD"), "MEDIUM": ("MEDIUM", "EASY", "HARD"),
             "HARD": ("HARD", "MEDIUM", "EASY")}


def _cfg(state: dict[str, Any]) -> dict[str, Any]:
    return state["config"]["mode"]


def _slot_order(state: dict[str, Any], pids) -> list[str]:
    return sorted(pids, key=lambda pid: participants(state)[pid]["slot"])


def alive(state: dict[str, Any]) -> list[str]:
    return _slot_order(state, [pid for pid, p in participants(state).items()
                               if p.get("survival_status") != SurvivalStatus.ELIMINATED])


def init(state: dict[str, Any]) -> None:
    state["match_phase"] = Phase.SURVIVAL_NORMAL.value
    state["unresolved_round_streak"] = 0
    state["used_gids"] = []
    state["eliminations"] = []  # [{"round_index", "pids", "reason"}] in elimination order
    state["next_round_spec"] = {"kind": RoundKind.NORMAL.value}


# ---------------------------------------------------------------------------------------------- round opening


def on_round_opened(state: dict[str, Any]) -> None:
    for p in participants(state).values():
        p["answered_this_round"] = False
        if p.get("survival_status") in (SurvivalStatus.SURVIVED, SurvivalStatus.PROTECTED):
            p["survival_status"] = SurvivalStatus.ACTIVE.value
    used = list(state.get("used_gids") or [])
    used.append(current_round(state)["gid"])
    state["used_gids"] = used


def _normal_difficulty(state: dict[str, Any], keys: Keyring, active_count: int) -> str:
    """Server-configured progression by active count (spec §4.4), deterministic per match and round."""
    cfg = _cfg(state)
    index = int(state.get("round_index", 0)) + 1
    roll = random.Random(int.from_bytes(keys.resolver.digest(f"difficulty:{state['match_id']}:{index}")[:8],
                                        "big")).random()
    if active_count >= 8:
        return "EASY" if roll < cfg.get("easy_weight_8_10", 0.65) else "MEDIUM"
    if active_count >= 5:
        return "MEDIUM"
    if active_count >= 3:
        return "HARD" if roll < cfg.get("hard_weight_3_4", 0.65) else "MEDIUM"
    return "HARD"


def _take_item(state: dict[str, Any], difficulty: str) -> dict[str, Any] | None:
    """Fresh question of the wanted band (falling back to neighbours); never repeats a question group."""
    used = set(state.get("used_gids") or [])
    pools = (state.get("plan") or {}).get("pools") or {}
    for band in _FALLBACK[difficulty]:
        items = list(pools.get(band) or [])
        for position, item in enumerate(items):
            if item["gid"] not in used:
                pools[band] = items[:position] + items[position + 1:]
                state["plan"] = {**(state.get("plan") or {}), "pools": pools}
                return item
    return None


def pool_remaining(state: dict[str, Any]) -> int:
    used = set(state.get("used_gids") or [])
    return sum(1 for items in ((state.get("plan") or {}).get("pools") or {}).values() for i in items or []
               if i["gid"] not in used)


def next_round(state: dict[str, Any], keys: Keyring):
    if state.get("winner_pid") or state.get("deterministic_order"):
        return None
    remaining = alive(state)
    if len(remaining) <= 1:
        if remaining:
            _declare_winner(state, remaining[0])
        return None
    spec = state.get("next_round_spec") or {"kind": RoundKind.NORMAL.value}
    kind = RoundKind(spec["kind"])
    cfg = _cfg(state)
    if kind == RoundKind.NORMAL:
        state["match_phase"] = Phase.SURVIVAL_NORMAL.value
        difficulty = _normal_difficulty(state, keys, len(remaining))
        duration = cfg["seconds"] * 1000
    else:
        state["match_phase"] = (Phase.SURVIVAL_RESCUE if kind == RoundKind.RESCUE else Phase.SURVIVAL_TIEBREAK).value
        difficulty = spec["difficulty"]
        duration = int(spec["duration_ms"])
    item = _take_item(state, difficulty)
    if item is None:
        # Inventory exhausted mid-match (refill failed): end deterministically rather than loop.
        _deterministic_finish(state, remaining, "INVENTORY_EXHAUSTED")
        return None
    if kind == RoundKind.TIEBREAK:
        state["tiebreak_start_active"] = remaining
    state["next_round_spec"] = {"kind": RoundKind.NORMAL.value}
    return item, kind, duration, remaining


def after_open(state: dict[str, Any], now_ms: int, result: StepResult) -> None:
    """Background refill when the server-only reserve runs low (spec §26.2)."""
    reserve = int(_cfg(state).get("reserve_questions", 10))
    batch = int(state.get("refill_batches", 0))
    if pool_remaining(state) < reserve and not state.get("refill_pending"):
        state["refill_pending"] = True
        result.effects.append(Effect("REFILL_QUESTIONS", now_ms, {"batch": batch + 1}))


def add_pool_items(state: dict[str, Any], batch: int, items_by_band: dict[str, list[dict[str, Any]]],
                   now_ms: int) -> StepResult:
    result = StepResult()
    if int(state.get("refill_batches", 0)) >= batch or state.get("state") in (
            MatchState.FINISHED_PENDING_SETTLEMENT, MatchState.FINISHED, MatchState.CANCELLED):
        state["refill_pending"] = False
        result.changed = True
        return result
    pools = dict((state.get("plan") or {}).get("pools") or {})
    known = set(state.get("used_gids") or []) | {i["gid"] for items in pools.values() for i in items or []}
    for band, items in items_by_band.items():
        fresh = [i for i in items if i["gid"] not in known]
        known |= {i["gid"] for i in fresh}
        pools[band] = list(pools.get(band) or []) + fresh
    state["plan"] = {**(state.get("plan") or {}), "pools": pools}
    state["refill_batches"] = batch
    state["refill_pending"] = False
    audit(state, now_ms, "REFILL_QUESTIONS", "REFILL")
    result.changed = True
    return result


# ---------------------------------------------------------------------------------------------- answers


def _sync_bot_locks(state: dict[str, Any], now_ms: int) -> None:
    """Bots show a lock once their planned response time has passed (correctness stays hidden)."""
    rnd = current_round(state)
    for pid, plan in (state.get("bot_plans") or {}).items():
        if plan.get("round_id") == rnd.get("round_id") and plan.get("will_answer") \
                and plan["response_at_ms"] <= now_ms and pid in (rnd.get("eligible") or []):
            participants(state)[pid]["answered_this_round"] = True


def apply_due_bot_winner(state: dict[str, Any], due_ms: int, now_ms: int, result: StepResult, source: str) -> bool:
    return False  # no early winner: correctness is hidden until resolution


def on_answer(state: dict[str, Any], pid: str, answer: dict[str, Any], received_at_ms: int, result: StepResult,
              source: str) -> None:
    _sync_bot_locks(state, received_at_ms)
    bump(state, received_at_ms, "LOCK_ANSWER", source)


def on_leave(state: dict[str, Any], pid: str, now_ms: int, result: StepResult) -> None:
    """Explicit Leave is abandonment: an alive leaver is eliminated immediately, no re-entry (spec §25.2)."""
    participant = participants(state)[pid]
    participant["active"] = False
    if participant.get("survival_status") == SurvivalStatus.ELIMINATED:
        return
    participant["survival_status"] = SurvivalStatus.ELIMINATED.value
    _record_elimination(state, [pid], "LEFT")
    remaining = alive(state)
    if len(remaining) == 1 and state.get("state") not in (MatchState.FINISHED_PENDING_SETTLEMENT,):
        _declare_winner(state, remaining[0])
        engine.finish(state, now_ms, result, "LAST_SURVIVOR")


# ---------------------------------------------------------------------------------------------- resolution


def _record_elimination(state: dict[str, Any], pids: list[str], reason: str) -> None:
    if not pids:
        return
    log = list(state.get("eliminations") or [])
    log.append({"round_index": int(state.get("round_index", 0)), "pids": _slot_order(state, pids), "reason": reason})
    state["eliminations"] = log


def _declare_winner(state: dict[str, Any], pid: str) -> None:
    state["winner_pid"] = pid
    participants(state)[pid]["survival_status"] = SurvivalStatus.WINNER.value


def _deterministic_key(state: dict[str, Any], pid: str) -> tuple:
    p = participants(state)[pid]
    return (-int(p.get("correct_rounds", 0)), int(p.get("correct_ms_sum", 0)), state["tiebreak_hmac"][pid])


def _deterministic_finish(state: dict[str, Any], candidates: list[str], reason: str) -> None:
    """Correct rounds desc, correct response-time sum asc, HMAC(tiebreak_key, match_id:uid) asc (spec §4.3)."""
    order = sorted(candidates, key=lambda pid: _deterministic_key(state, pid))
    state["deterministic_order"] = order
    state["deterministic_reason"] = reason
    for pid in order[1:]:
        participants(state)[pid]["survival_status"] = SurvivalStatus.ELIMINATED.value
    _declare_winner(state, order[0])


def _project_bot_answers(state: dict[str, Any], ends_at_ms: int) -> None:
    rnd = current_round(state)
    answers = dict(rnd.get("answers") or {})
    for pid, plan in (state.get("bot_plans") or {}).items():
        if plan.get("round_id") != rnd["round_id"] or pid not in (rnd.get("eligible") or []) or pid in answers:
            continue
        if not plan.get("will_answer") or plan["response_at_ms"] >= ends_at_ms:
            continue
        answers[pid] = {"concept_id": plan["selected_concept_id"], "received_at_ms": plan["response_at_ms"],
                        "correct": plan["selected_concept_id"] == rnd["correct"],
                        "request_id": f"bot:{plan['commit_hash'][:12]}"}
        participants(state)[pid]["answered_this_round"] = True
        participants(state)[pid]["answered_rounds"] = int(participants(state)[pid].get("answered_rounds", 0)) + 1
    rnd["answers"] = answers


def expire_round(state: dict[str, Any], ends_at_ms: int, now_ms: int, result: StepResult, source: str) -> None:
    rnd = current_round(state)
    kind = RoundKind(rnd["kind"])
    _project_bot_answers(state, ends_at_ms)
    answers = rnd.get("answers") or {}
    contenders = [pid for pid in rnd.get("eligible") or []
                  if participants(state)[pid].get("survival_status") != SurvivalStatus.ELIMINATED]
    correct = [pid for pid in contenders if pid in answers and answers[pid]["correct"]]
    wrong = [pid for pid in contenders if pid in answers and not answers[pid]["correct"]]
    silent = [pid for pid in contenders if pid not in answers]
    for pid in correct:
        p = participants(state)[pid]
        p["correct_rounds"] = int(p.get("correct_rounds", 0)) + 1
        p["correct_ms_sum"] = int(p.get("correct_ms_sum", 0)) + (answers[pid]["received_at_ms"] - rnd["starts_at_ms"])
        p["score"] = p["correct_rounds"]
    outcome: dict[str, Any] = {"survived": correct, "eliminated": [], "protected": []}
    cfg = _cfg(state)
    rescue_ms = int(cfg.get("rescue_seconds", 15)) * 1000

    def eliminate(pids: list[str], reason: str) -> None:
        for pid in pids:
            participants(state)[pid]["survival_status"] = SurvivalStatus.ELIMINATED.value
            append_event(state, now_ms, EventType.ELIMINATED, pid)
        _record_elimination(state, pids, reason)
        outcome["eliminated"] = outcome["eliminated"] + pids

    if kind == RoundKind.TIEBREAK:
        # Final tiebreak: wrong and no-answer both eliminate; a non-unique result ends deterministically.
        eliminate(wrong + silent, "TIEBREAK")
        for pid in correct:
            participants(state)[pid]["survival_status"] = SurvivalStatus.SURVIVED.value
        if len(correct) == 1:
            _declare_winner(state, correct[0])
            outcome["resolution"] = "TIEBREAK_WINNER"
        else:
            pool = correct if correct else list(state.get("tiebreak_start_active") or contenders)
            _deterministic_finish(state, pool, "TIEBREAK_UNRESOLVED")
            outcome["resolution"] = "DETERMINISTIC"
            outcome["deterministic_order"] = state["deterministic_order"]
        state["unresolved_round_streak"] = 0 if len(correct) == 1 else int(state.get("unresolved_round_streak", 0)) + 1
    elif correct:
        eliminate(wrong + silent, "NORMAL")
        for pid in correct:
            participants(state)[pid]["survival_status"] = SurvivalStatus.SURVIVED.value
        state["unresolved_round_streak"] = 0
        state["next_round_spec"] = {"kind": RoundKind.NORMAL.value}
        outcome["resolution"] = "NORMAL"
        append_event(state, now_ms, EventType.SURVIVED, value=len(correct))
    else:
        streak = int(state.get("unresolved_round_streak", 0)) + 1
        state["unresolved_round_streak"] = streak
        if wrong:
            # All submitted answers wrong: wrong answers are protected for this one round (spec §4.3 rule 1).
            eliminate(silent, "NO_ANSWER")
            for pid in wrong:
                participants(state)[pid]["survival_status"] = SurvivalStatus.PROTECTED.value
            outcome["protected"] = wrong
            outcome["resolution"] = "ALL_WRONG"
            lower = {"HARD": "MEDIUM", "MEDIUM": "EASY", "EASY": "EASY"}[rnd["difficulty"]]
            state["next_round_spec"] = {"kind": RoundKind.RESCUE.value, "difficulty": lower,
                                        "duration_ms": int(cfg["seconds"]) * 1000}
        else:
            # Nobody answered: one fresh 15-second Easy rescue round (rule 2); nobody is eliminated.
            for pid in contenders:
                participants(state)[pid]["survival_status"] = SurvivalStatus.PROTECTED.value
            outcome["protected"] = contenders
            outcome["resolution"] = "NO_ANSWERS"
            state["next_round_spec"] = {"kind": RoundKind.RESCUE.value, "difficulty": "EASY",
                                        "duration_ms": rescue_ms}
        append_event(state, now_ms, EventType.RESCUE, value=streak)
        remaining = alive(state)
        if len(remaining) == 1:
            _declare_winner(state, remaining[0])
        elif streak >= int(cfg.get("unresolved_round_cap", 3)):
            # Rule 3: one final 15-second Easy SURVIVAL_TIEBREAK round.
            state["next_round_spec"] = {"kind": RoundKind.TIEBREAK.value, "difficulty": "EASY",
                                        "duration_ms": rescue_ms}
            append_event(state, now_ms, EventType.TIEBREAK)
    remaining = alive(state)
    if not state.get("winner_pid") and len(remaining) == 1:
        _declare_winner(state, remaining[0])
    rnd["outcome"] = outcome
    engine.close_round(state, now_ms, result, source, int(cfg["reveal_ms"]))


# ---------------------------------------------------------------------------------------------- results


def final_standings(state: dict[str, Any]) -> dict[str, Any]:
    """Winner first; deterministic order when used; then elimination bands, latest band ranks higher."""
    placements: dict[str, int] = {}
    order: list[str] = []
    bands: list[list[str]] = []
    deterministic = list(state.get("deterministic_order") or [])
    if deterministic:
        for pid in deterministic:
            bands.append([pid])
    else:
        top = alive(state)
        winner = state.get("winner_pid")
        if winner:
            bands.append([winner])
            rest = [pid for pid in top if pid != winner]
            if rest:
                bands.append(rest)
        elif top:
            # Finished early (e.g. every human left): order the still-alive players deterministically.
            bands.extend([pid] for pid in sorted(top, key=lambda pid: _deterministic_key(state, pid)))
    placed = {pid for band in bands for pid in band}
    for entry in reversed(state.get("eliminations") or []):
        band = [pid for pid in entry["pids"] if pid not in placed]
        if band:
            bands.append(band)
            placed |= set(band)
    leftovers = [pid for pid in _slot_order(state, participants(state)) if pid not in placed]
    if leftovers:
        bands.append(leftovers)
    place = 1
    for band in bands:
        for pid in band:
            placements[pid] = place
            order.append(pid)
        place += len(band)
    return {
        "order": order,
        "placements": placements,
        "bands": bands,
        "scores": {pid: int(participants(state)[pid].get("correct_rounds", 0)) for pid in order},
        "wins": {pid: int(participants(state)[pid].get("correct_rounds", 0)) for pid in order},
        "winner": order[0] if order else None,
        "deterministic": bool(deterministic),
        "rounds_played": int(state.get("round_index", 0)),
    }


def public_extras(state: dict[str, Any]) -> dict[str, Any]:
    status = state.get("state")
    extras: dict[str, Any] = {"unresolved_round_streak": int(state.get("unresolved_round_streak", 0))}
    # Alive count only changes at resolution, so it never leaks hidden correctness during ROUND_ACTIVE.
    extras["active_count"] = len(alive(state))
    if status in (MatchState.ROUND_RESOLVE,) and current_round(state).get("outcome"):
        extras["round_outcome"] = current_round(state)["outcome"]
    return extras


def display_round_number(state: dict[str, Any]) -> int:
    return int(state.get("round_index", 0))


def reveal_payload(state: dict[str, Any]) -> dict[str, Any]:
    rnd = current_round(state)
    text = next(o["text"] for o in rnd["options"] if o["concept_id"] == rnd["correct"])
    outcome = rnd.get("outcome") or {}
    return {"concept_id": rnd["correct"], "text": text, "resolution": outcome.get("resolution"),
            "survived": outcome.get("survived") or [], "eliminated": outcome.get("eliminated") or [],
            "protected": outcome.get("protected") or []}


def public_result(state: dict[str, Any]) -> dict[str, Any]:
    result = state["result"]
    return {"standings": [{"pid": pid, "place": result["placements"][pid], "score": result["scores"][pid],
                           "wins": result["wins"][pid]} for pid in result["order"]],
            "winner_pid": result.get("winner"), "deterministic": result.get("deterministic", False)}


def own_answer_status(state: dict[str, Any], pid: str, answer: dict[str, Any] | None, eligible: bool) -> AnswerStatus:
    if not eligible and answer is None:
        return AnswerStatus.INELIGIBLE
    if answer is None:
        return AnswerStatus.NOT_ANSWERED
    if state.get("state") in (MatchState.ROUND_LOADING, MatchState.ROUND_ACTIVE):
        return AnswerStatus.LOCKED  # correctness hidden until resolution (spec §4.1)
    return AnswerStatus.ANSWERED_CORRECT if answer["correct"] else AnswerStatus.ANSWERED_WRONG
