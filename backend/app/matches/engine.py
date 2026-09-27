"""Pure live-match state machine (spec §20.4, §22, §24).

Every function mutates a *copy* of the authoritative state dict and is run inside the canonical RTDB root
transaction; it performs no I/O, so retries are safe. Side effects are returned as ``Effect`` values and
executed only after commit.
"""

from __future__ import annotations

import copy
import logging
import random
from typing import Any

from app.bots.planner import plan_bot_round
from app.common.errors import ErrorCode
from app.common.keys import Keyring
from app.common.server_config import BotProfileConfig
from app.common.tasks import TaskKind
from app.matches.model import (
    DISPLAY_POSITIONS,
    SCHEMA_VERSION,
    Effect,
    EventType,
    MatchState,
    Mode,
    RoundKind,
    StepResult,
    SurvivalStatus,
    append_event,
    bump,
    current_round,
    humans,
    participants,
    pid_for_uid,
)

# Answers received before a deadline (or before a planned bot win) may still be in flight on another instance;
# background resolvers wait this long before closing a round so a timely answer is never lost to scheduling.
GRACE_MS = 300
RECOVERY_DELAY_MS = GRACE_MS + 250
START_DELAY_MS = 50
ADVANCE_DELAY_MS = 50

log = logging.getLogger("oltivra.engine")


def _rules(mode: str):
    if mode == Mode.QUICK:
        from app.quick_battle import rules
    else:
        from app.survival import rules
    return rules


# ---------------------------------------------------------------------------------------------- creation


def create_match_state(
    *,
    keys: Keyring,
    match_id: str,
    shard_id: str,
    mode: Mode,
    language: str,
    region: str,
    roster: list[dict[str, Any]],
    plan: dict[str, Any],
    config_snapshot: dict[str, Any],
    bot_profiles: dict[str, dict[str, Any]],
    reaction_ids: list[str],
    ranked: dict[str, Any],
    source: str,
    now_ms: int,
) -> tuple[dict[str, Any], StepResult]:
    """Build the canonical root in PREPARING and immediately publish round 1 (ROUND_LOADING)."""
    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "match_id": match_id,
        "shard_id": shard_id,
        "mode": mode.value,
        "language": language,
        "region": region,
        "source": source,
        "state": MatchState.PREPARING.value,
        "state_version": 0,
        "event_seq": 0,
        "round_index": 0,
        "created_at_ms": now_ms,
        "config": config_snapshot,
        "ranked": ranked,
        "bot_profiles": bot_profiles,
        "reaction_ids": reaction_ids,
        "plan": plan,
        "shown_qids": [],
        "round_log": [],
        "participants": {},
    }
    state["tiebreak_hmac"] = {}
    for slot, member in enumerate(roster):
        state["participants"][member["pid"]] = {
            "slot": slot,
            "kind": member["kind"],
            **({"uid": member["uid"]} if member["kind"] == "HUMAN" else {"bot_id": member["bot_id"]}),
            "username": member["username"],
            "avatar_id": member["avatar_id"],
            "frame_id": member.get("frame_id", "frame_none"),
            "pre_match_mmr": member["pre_match_mmr"],
            "score": 0,
            "wins": 0,
            "win_ms_sum": 0,
            "correct_rounds": 0,
            "correct_ms_sum": 0,
            "answered_rounds": 0,
            "active": True,
            "left": False,
            "survival_status": SurvivalStatus.ACTIVE.value,
        }
        identity = member.get("uid") or member["bot_id"]
        state["tiebreak_hmac"][member["pid"]] = keys.tiebreak.hexdigest(f"{match_id}:{identity}")
    _rules(mode).init(state)
    result = StepResult(changed=True)
    bump(state, now_ms, "CREATE", source)
    _advance_to_next_round(state, keys, now_ms, result, "CREATE")
    return state, result


# ---------------------------------------------------------------------------------------------- rounds


def _option_order(keys: Keyring, match_id: str, round_id: str, pid: str, concepts: list[str]) -> dict[str, str]:
    rng = random.Random(int.from_bytes(keys.resolver.digest(f"options:{match_id}:{round_id}:{pid}")[:8], "big"))
    shuffled = list(concepts)
    rng.shuffle(shuffled)
    return dict(zip(DISPLAY_POSITIONS, shuffled, strict=True))


def open_round(state: dict[str, Any], keys: Keyring, now_ms: int, item: dict[str, Any], kind: RoundKind,
               duration_ms: int, eligible: list[str], result: StepResult) -> None:
    index = int(state.get("round_index", 0)) + 1
    match_id = state["match_id"]
    # A substituted round gets a fresh ID so its tasks are never deduplicated against the replaced one.
    attempt = int((state.get("round_attempts") or {}).get(str(index), 0))
    seed = f"round:{match_id}:{index}" + (f":{attempt}" if attempt else "")
    round_id = f"r{index:02d}-{keys.resolver.hexdigest(seed)[:10]}"
    lead = state["config"]["mode"]["round_lead_ms"]
    starts = now_ms + lead
    ends = starts + duration_ms
    concepts = [o["concept_id"] for o in item["options"]]
    orders = {pid: _option_order(keys, match_id, round_id, pid, concepts)
              for pid, p in humans(state).items() if pid in eligible}
    bot_plans: dict[str, Any] = {}
    for pid, p in participants(state).items():
        if p["kind"] != "BOT" or pid not in eligible:
            continue
        profile = BotProfileConfig.model_validate(state["bot_profiles"][pid])
        bot_plans[pid] = plan_bot_round(
            keys.bot_plan, match_id=match_id, round_id=round_id, bot_id=p["bot_id"],
            question_version=f"{item['gid']}:{item['v']}", profile=profile, difficulty=item["difficulty"],
            option_concepts=concepts, correct_concept=item["correct"], starts_at_ms=starts, duration_ms=duration_ms,
            reaction_ids=state.get("reaction_ids") or [],
            reaction_probability=float((state["config"].get("bots") or {}).get("reaction_probability", 0.15)))
    state["round_index"] = index
    state["round"] = {
        "round_id": round_id,
        "index": index,
        "kind": kind.value,
        "qid": item["qid"],
        "gid": item["gid"],
        "v": item["v"],
        "difficulty": item["difficulty"],
        "category_id": item["category_id"],
        "text": item["text"],
        "options": item["options"],
        "correct": item["correct"],
        "media": item.get("media"),
        "starts_at_ms": starts,
        "ends_at_ms": ends,
        "duration_ms": duration_ms,
        "eligible": eligible,
        "option_orders": orders,
        "answers": {},
        "reactions": {},
        "resolved": False,
    }
    state["bot_plans"] = bot_plans
    state["state"] = MatchState.ROUND_LOADING.value
    state["next_server_event_at_ms"] = starts
    shown = list(state.get("shown_qids") or [])
    shown.append(item["qid"])
    state["shown_qids"] = shown
    _rules(state["mode"]).on_round_opened(state)
    parts = (match_id, round_id)
    result.effects.append(Effect(TaskKind.ROUND_START.value, starts + START_DELAY_MS, {"round_id": round_id,
                                                                                      "dedupe": parts}))
    result.effects.append(Effect(TaskKind.ROUND_RECOVERY.value, ends + RECOVERY_DELAY_MS, {"round_id": round_id,
                                                                                          "dedupe": parts}))
    if state["mode"] == Mode.QUICK:
        earliest = _earliest_correct_bot(state)
        if earliest is not None:
            result.effects.append(Effect(TaskKind.BOT_WINNER.value, earliest[1], {"round_id": round_id,
                                                                                 "dedupe": parts}))
    if item.get("media"):
        result.effects.append(Effect("SIGN_MEDIA", now_ms, {"round_id": round_id, "path": item["media"]["path"],
                                                            "expires_at_ms": ends + 30_000}))


def _earliest_correct_bot(state: dict[str, Any]) -> tuple[str, int] | None:
    rnd = current_round(state)
    best: tuple[str, int] | None = None
    for pid, plan in (state.get("bot_plans") or {}).items():
        if plan.get("round_id") != rnd.get("round_id") or not plan.get("will_be_correct"):
            continue
        if pid not in (rnd.get("eligible") or []):
            continue
        if plan["response_at_ms"] >= rnd["ends_at_ms"]:
            continue
        if best is None or plan["response_at_ms"] < best[1]:
            best = (pid, plan["response_at_ms"])
    return best


def _substitute_unsigned_media(state: dict[str, Any], keys: Keyring, now_ms: int, result: StepResult,
                               source: str) -> bool:
    """A media question whose image never arrived is replaced by a text-only reserve before it becomes
    answerable (spec §9.1, §22.2); it is never played without its image. Returns True when replaced."""
    rnd = current_round(state)
    if not rnd.get("media") or rnd.get("signed_image_url"):
        return False
    rules = _rules(state["mode"])
    replacement = rules.media_substitute(state, rnd)
    if replacement is None:
        log.error("media_substitute_unavailable", extra={"match_id": state["match_id"], "qid": rnd.get("qid")})
        return False
    kind = RoundKind(rnd["kind"])
    attempts = dict(state.get("round_attempts") or {})
    attempts[str(rnd["index"])] = int(attempts.get(str(rnd["index"]), 0)) + 1
    state["round_attempts"] = attempts
    state["round_index"] = int(state.get("round_index", 1)) - 1
    rules.rewind_round(state, rnd)
    open_round(state, keys, now_ms, replacement, kind, int(rnd["duration_ms"]), list(rnd.get("eligible") or []),
               result)
    if hasattr(rules, "after_open"):
        rules.after_open(state, now_ms, result)
    bump(state, now_ms, "MEDIA_SUBSTITUTED", source)
    result.changed = True
    return True


def _advance_to_next_round(state: dict[str, Any], keys: Keyring, now_ms: int, result: StepResult,
                           source: str) -> None:
    spec = _rules(state["mode"]).next_round(state, keys)
    if spec is None:
        finish(state, now_ms, result, source)
        return
    item, kind, duration_ms, eligible = spec
    open_round(state, keys, now_ms, item, kind, duration_ms, eligible, result)
    rules = _rules(state["mode"])
    if hasattr(rules, "after_open"):
        rules.after_open(state, now_ms, result)
    bump(state, now_ms, f"OPEN_{kind.value}", source)


def close_round(state: dict[str, Any], now_ms: int, result: StepResult, source: str, reveal_ms: int) -> None:
    """Enter ROUND_REVEAL / ROUND_RESOLVE and schedule the advance wake-up."""
    rnd = current_round(state)
    rnd["resolved"] = True
    rnd["closed_at_ms"] = now_ms
    reveal_ends = now_ms + reveal_ms
    rnd["reveal_ends_at_ms"] = reveal_ends
    state["state"] = (MatchState.ROUND_REVEAL if state["mode"] == Mode.QUICK else MatchState.ROUND_RESOLVE).value
    state["next_server_event_at_ms"] = reveal_ends
    _bot_reactions(state, now_ms)
    _log_round(state)
    bump(state, now_ms, "CLOSE_ROUND", source)
    result.effects.append(Effect(TaskKind.ROUND_ADVANCE.value, reveal_ends + ADVANCE_DELAY_MS,
                                 {"round_id": rnd["round_id"], "dedupe": (state["match_id"], rnd["round_id"],
                                                                          "advance")}))


def _bot_reactions(state: dict[str, Any], now_ms: int) -> None:
    """Precommitted optional bot reactions surface at reveal, like a human reacting to the result."""
    rnd = current_round(state)
    reactions = dict(rnd.get("reactions") or {})
    for pid, plan in sorted((state.get("bot_plans") or {}).items()):
        reaction = plan.get("optional_reaction_id")
        if plan.get("round_id") != rnd.get("round_id") or not reaction or pid in reactions:
            continue
        if reaction not in (state.get("reaction_ids") or []):
            continue
        reactions[pid] = reaction
        append_event(state, now_ms, EventType.REACTION, pid, reaction)
    rnd["reactions"] = reactions


def _log_round(state: dict[str, Any]) -> None:
    """Compact per-round record used by settlement for human question statistics and category stats."""
    rnd = current_round(state)
    answers = {}
    for pid, answer in (rnd.get("answers") or {}).items():
        answers[pid] = {"c": bool(answer["correct"]), "ms": answer["received_at_ms"] - rnd["starts_at_ms"]}
    log = list(state.get("round_log") or [])
    log.append({
        "round_id": rnd["round_id"], "qid": rnd["qid"], "gid": rnd["gid"], "v": rnd["v"], "kind": rnd["kind"],
        "difficulty": rnd["difficulty"], "category_id": rnd["category_id"], "eligible": rnd.get("eligible") or [],
        "answers": answers, "winner": rnd.get("winner_pid"), "closed_at_ms": rnd.get("closed_at_ms"),
        "starts_at_ms": rnd["starts_at_ms"],
        "resolution": (rnd.get("outcome") or {}).get("resolution"),
        "eliminated": (rnd.get("outcome") or {}).get("eliminated") or [],
    })
    state["round_log"] = log


def finish(state: dict[str, Any], now_ms: int, result: StepResult, source: str) -> None:
    standings = _rules(state["mode"]).final_standings(state)
    state["result"] = standings
    state["state"] = MatchState.FINISHED_PENDING_SETTLEMENT.value
    state["finished_at_ms"] = now_ms
    state["next_server_event_at_ms"] = 0
    state.pop("bot_plans", None)
    bump(state, now_ms, "FINISH", source)
    result.effects.append(Effect("START_SETTLEMENT", now_ms, {}))


def cancel(state: dict[str, Any], now_ms: int, reason: str, source: str) -> StepResult:
    result = StepResult(changed=True)
    state["state"] = MatchState.CANCELLED.value
    state["cancel_reason"] = reason
    state["next_server_event_at_ms"] = 0
    state.pop("bot_plans", None)
    bump(state, now_ms, f"CANCEL_{reason}", source)
    result.effects.append(Effect("START_SETTLEMENT", now_ms, {"cancelled": True}))
    return result


# ---------------------------------------------------------------------------------------------- resolver


def resolve_due(state: dict[str, Any], keys: Keyring, now_ms: int, source: str,
                result: StepResult | None = None, grace_ms: int = GRACE_MS) -> StepResult:
    """``resolve_round_if_due``: apply every transition that is due at ``now_ms`` (spec §20.4).

    ``grace_ms`` delays closing an active round (deadline or planned bot win) for background callers; the
    answer path passes 0 with its own receipt time, so ordering is decided by authoritative receipt.
    """
    result = result or StepResult()
    due_ms = now_ms - grace_ms
    rules = _rules(state["mode"])
    for _ in range(64):  # bounded catch-up loop
        status = state.get("state")
        rnd = current_round(state)
        if status == MatchState.ROUND_LOADING and now_ms >= rnd["starts_at_ms"]:
            if _substitute_unsigned_media(state, keys, now_ms, result, source):
                continue
            state["state"] = MatchState.ROUND_ACTIVE.value
            earliest = _earliest_correct_bot(state) if state["mode"] == Mode.QUICK else None
            event_at = min(earliest[1], rnd["ends_at_ms"]) if earliest else rnd["ends_at_ms"]
            state["next_server_event_at_ms"] = event_at + GRACE_MS
            bump(state, now_ms, "ROUND_ACTIVE", source)
            result.changed = True
            continue
        if status == MatchState.ROUND_ACTIVE:
            if rules.apply_due_bot_winner(state, due_ms, now_ms, result, source):
                result.changed = True
                continue
            if due_ms >= rnd["ends_at_ms"]:
                rules.expire_round(state, rnd["ends_at_ms"], now_ms, result, source)
                result.changed = True
                continue
            return result
        if status in (MatchState.ROUND_REVEAL, MatchState.ROUND_RESOLVE) and now_ms >= rnd["reveal_ends_at_ms"]:
            _advance_to_next_round(state, keys, now_ms, result, source)
            result.changed = True
            continue
        return result
    return result


def _reject(result: StepResult, code: ErrorCode, **detail: Any) -> StepResult:
    result.outcome = {"error": code.value, **detail}
    return result


def apply_answer(state: dict[str, Any], keys: Keyring, *, uid: str, round_id: str, option_id: str,
                 received_at_ms: int, request_id: str) -> StepResult:
    """Authoritative answer sequence (spec §22.3, §28.2). Errors are returned, not raised, so that any
    reconciliation performed before validation is still committed."""
    result = resolve_due(state, keys, received_at_ms, "ANSWER", grace_ms=0)
    pid = pid_for_uid(state, uid)
    if pid is None:
        return _reject(result, ErrorCode.NOT_MATCH_PARTICIPANT)
    rnd = current_round(state)
    existing = (rnd.get("answers") or {}).get(pid) if rnd.get("round_id") == round_id else None
    if existing is not None:
        if existing.get("request_id") == request_id:  # idempotent replay of the original outcome
            if existing.get("concept_id") != option_id:  # same key, different payload (spec §19.1)
                return _reject(result, ErrorCode.IDEMPOTENCY_KEY_REUSED)
            result.outcome = {"accepted": True, "replay": True, **_answer_view(state, pid, existing)}
            return result
        return _reject(result, ErrorCode.ANSWER_ALREADY_SUBMITTED)
    if rnd.get("round_id") != round_id:
        return _reject(result, ErrorCode.ROUND_NOT_ACTIVE, reason="stale_round")
    if state.get("state") != MatchState.ROUND_ACTIVE:
        code = ErrorCode.ROUND_EXPIRED if received_at_ms >= rnd.get("ends_at_ms", 0) else ErrorCode.ROUND_NOT_ACTIVE
        return _reject(result, code)
    if received_at_ms >= rnd["ends_at_ms"]:
        return _reject(result, ErrorCode.ROUND_EXPIRED)
    participant = participants(state)[pid]
    if pid not in (rnd.get("eligible") or []) or participant.get("left") or not participant.get("active"):
        return _reject(result, ErrorCode.FORBIDDEN, reason="not_eligible")
    order = (rnd.get("option_orders") or {}).get(pid) or {}
    if option_id not in order.values():
        return _reject(result, ErrorCode.INVALID_OPTION)
    correct = option_id == rnd["correct"]
    answer = {"concept_id": option_id, "received_at_ms": received_at_ms, "correct": correct,
              "request_id": request_id}
    rnd.setdefault("answers", {})
    rnd["answers"] = {**(rnd.get("answers") or {}), pid: answer}
    participant["answered_this_round"] = True
    participant["answered_rounds"] = int(participant.get("answered_rounds", 0)) + 1
    _rules(state["mode"]).on_answer(state, pid, answer, received_at_ms, result, "ANSWER")
    result.changed = True
    stored = (current_round(state).get("answers") or {}).get(pid, answer) \
        if current_round(state).get("round_id") == round_id else answer
    result.outcome = {"accepted": True, "replay": False, **_answer_view(state, pid, stored)}
    return result


def _answer_view(state: dict[str, Any], pid: str, answer: dict[str, Any]) -> dict[str, Any]:
    view: dict[str, Any] = {"state_version": state.get("state_version")}
    if state["mode"] == Mode.QUICK:
        view["correct"] = answer["correct"]
        view["score_delta"] = answer.get("score_delta", 0)
    else:
        view["locked"] = True  # correctness stays hidden until resolution (spec §4.1)
    return view


def apply_leave(state: dict[str, Any], keys: Keyring, uid: str, now_ms: int) -> StepResult:
    """Explicit Leave after start records voluntary abandonment (spec §25). The match continues."""
    result = resolve_due(state, keys, now_ms, "LEAVE")
    pid = pid_for_uid(state, uid)
    if pid is None:
        return _reject(result, ErrorCode.NOT_MATCH_PARTICIPANT)
    participant = participants(state)[pid]
    if participant.get("left"):
        result.outcome = {"left": True, "replay": True}
        return result
    if state.get("state") in (MatchState.FINISHED_PENDING_SETTLEMENT, MatchState.FINISHED, MatchState.CANCELLED):
        result.outcome = {"left": True, "after_finish": True}
        return result
    participant["left"] = True
    participant["left_at_round"] = int(state.get("round_index", 0))
    participant["left_at_ms"] = now_ms
    append_event(state, now_ms, EventType.LEFT, pid)
    _rules(state["mode"]).on_leave(state, pid, now_ms, result)
    bump(state, now_ms, "LEAVE", "LEAVE")
    result.changed = True
    if not any(not p.get("left") for p in humans(state).values()):
        # Every human left: no one remains to play, finish immediately with current standings.
        if state.get("state") not in (MatchState.FINISHED_PENDING_SETTLEMENT.value,):
            finish(state, now_ms, result, "ALL_HUMANS_LEFT")
    result.outcome = {"left": True, "replay": False}
    return result


def attach_media(state: dict[str, Any], round_id: str, url: str, expires_at_ms: int, now_ms: int) -> StepResult:
    """Post-commit SIGN_MEDIA effect: publish the short-lived signed URL for the current round only."""
    result = StepResult()
    rnd = current_round(state)
    if rnd.get("round_id") != round_id or rnd.get("signed_image_url") or not rnd.get("media"):
        return result
    if state.get("state") not in (MatchState.ROUND_LOADING, MatchState.ROUND_ACTIVE):
        return result
    rnd["signed_image_url"] = url
    rnd["image_expires_at_ms"] = expires_at_ms
    bump(state, now_ms, "MEDIA_SIGNED", "SIGN_MEDIA")
    result.changed = True
    return result


def mark_settled(state: dict[str, Any], now_ms: int, status: str, by_uid: dict[str, Any]) -> StepResult:
    """Settlement committed: public FINISHED (or CANCELLED stays) and per-player results become visible."""
    result = StepResult()
    if (state.get("settlement") or {}).get("status") == status:
        return result
    state["settlement"] = {"status": status, "by_uid": by_uid, "settled_at_ms": now_ms}
    if state.get("state") == MatchState.FINISHED_PENDING_SETTLEMENT:
        state["state"] = MatchState.FINISHED.value
    state["next_server_event_at_ms"] = 0
    bump(state, now_ms, f"SETTLEMENT_{status}", "SETTLEMENT")
    result.changed = True
    return result


REACTABLE_STATES = (MatchState.ROUND_LOADING, MatchState.ROUND_ACTIVE, MatchState.ROUND_REVEAL,
                    MatchState.ROUND_RESOLVE)


def apply_reaction(state: dict[str, Any], keys: Keyring, *, uid: str, round_id: str, reaction_id: str, now_ms: int,
                   mutes: dict[str, list[str]] | None = None) -> StepResult:
    """One curated reaction per player (or spectator) per round (spec §5). Never affects scoring or timing."""
    result = resolve_due(state, keys, now_ms, "REACTION")
    if mutes is not None and mutes != (state.get("mutes") or {}):
        state["mutes"] = mutes
        result.changed = True
    pid = pid_for_uid(state, uid)
    if pid is None:
        return _reject(result, ErrorCode.NOT_MATCH_PARTICIPANT)
    participant = participants(state)[pid]
    if participant.get("left"):
        return _reject(result, ErrorCode.FORBIDDEN, reason="left_match")
    rnd = current_round(state)
    if state.get("state") not in REACTABLE_STATES or rnd.get("round_id") != round_id:
        return _reject(result, ErrorCode.ROUND_NOT_ACTIVE)
    if reaction_id not in (state.get("reaction_ids") or []):
        return _reject(result, ErrorCode.INVALID_REQUEST, reason="reaction_not_allowed")
    reactions = dict(rnd.get("reactions") or {})
    if pid in reactions:
        if reactions[pid] == reaction_id:
            result.outcome = {"accepted": True, "replay": True, "reaction_id": reaction_id}
            return result
        return _reject(result, ErrorCode.REACTION_ALREADY_USED)
    reactions[pid] = reaction_id
    rnd["reactions"] = reactions
    participant["reactions_sent"] = int(participant.get("reactions_sent", 0)) + 1
    append_event(state, now_ms, EventType.REACTION, pid, reaction_id)
    bump(state, now_ms, "REACTION", "REACTION")
    result.changed = True
    result.outcome = {"accepted": True, "replay": False, "reaction_id": reaction_id,
                      "state_version": state["state_version"]}
    return result


# ---------------------------------------------------------------------------------------------- projections


def designated_resolver(state: dict[str, Any], keys: Keyring) -> str | None:
    rnd = current_round(state)
    candidates = [(keys.resolver.hexdigest(f"{state['match_id']}:{rnd.get('round_id', '-')}:{p['uid']}"), pid)
                  for pid, p in humans(state).items() if not p.get("left")]
    return min(candidates)[1] if candidates else None


def project(state: dict[str, Any], keys: Keyring) -> dict[str, Any]:
    """Compute the full root: authoritative + public + player_private + access (spec §17.1–17.3)."""
    rnd = current_round(state)
    status = state.get("state")
    live_question = status in (MatchState.ROUND_LOADING, MatchState.ROUND_ACTIVE, MatchState.ROUND_REVEAL,
                               MatchState.ROUND_RESOLVE)
    revealed = status in (MatchState.ROUND_REVEAL, MatchState.ROUND_RESOLVE)
    rules = _rules(state["mode"])
    public: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "match_id": state["match_id"],
        "mode": state["mode"],
        "match_phase": state.get("match_phase"),
        "language": state["language"],
        "region": state["region"],
        "state": status,
        "state_version": state.get("state_version", 0),
        "config_version": state["config"].get("config_version", 1),
        "next_server_event_at_ms": state.get("next_server_event_at_ms", 0),
        "designated_resolver_pid": designated_resolver(state, keys),
        "participants": {},
        "events": state.get("events") or [],
        **rules.public_extras(state),
    }
    if live_question and rnd:
        public.update({
            "round_id": rnd["round_id"],
            "round_number": rules.display_round_number(state),
            "round_kind": rnd["kind"],
            "difficulty": rnd["difficulty"],
            "category_id": rnd["category_id"],
            "starts_at_ms": rnd["starts_at_ms"],
            "ends_at_ms": rnd["ends_at_ms"],
            "reveal_ends_at_ms": rnd.get("reveal_ends_at_ms", 0),
            "current_question": {
                "qid": rnd["qid"],
                "question_group_id": rnd["gid"],
                "question_version": rnd["v"],
                "text": rnd["text"],
                "options": {o["concept_id"]: o["text"] for o in rnd["options"]},
                **({"signed_image_url": rnd["signed_image_url"], "image_expires_at_ms": rnd["image_expires_at_ms"],
                    "image_aspect": rnd["media"]["aspect"]} if rnd.get("signed_image_url") and rnd.get("media")
                   else {}),
            },
        })
        if revealed:
            public["correct_answer_reveal"] = rules.reveal_payload(state)
    for pid, p in participants(state).items():
        # D3: bots are not distinguishable from humans in any client payload.
        public["participants"][pid] = {
            "display_name": p["username"],
            "avatar_id": p["avatar_id"],
            "frame_id": p.get("frame_id", "frame_none"),
            "active": bool(p.get("active")) and not p.get("left"),
            "left": bool(p.get("left")),
            "answer_locked": bool(p.get("answered_this_round")) if live_question else False,
            "score": p.get("score", 0),
            "survival_status": p.get("survival_status", SurvivalStatus.ACTIVE.value),
            "slot": p.get("slot", 0),
        }
    if state.get("result"):
        public["result_summary"] = rules.public_result(state)
    settlement = state.get("settlement") or {}
    if settlement.get("status"):
        public["settlement_status"] = settlement["status"]
        if settlement["status"] == "SETTLED":
            window = int(state["config"]["mode"].get("rematch_window_ms", 10_000))
            public["rematch_until_ms"] = int(settlement.get("settled_at_ms", 0)) + window
    private: dict[str, Any] = {}
    access: dict[str, str] = {}
    for pid, p in humans(state).items():
        uid = p["uid"]
        access[uid] = "participant"
        entry: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "pid": pid}
        if live_question and rnd:
            entry["round_id"] = rnd["round_id"]
            eligible = pid in (rnd.get("eligible") or []) and not p.get("left") and bool(p.get("active"))
            entry["eligible_to_answer"] = eligible and status in (MatchState.ROUND_LOADING, MatchState.ROUND_ACTIVE)
            order = (rnd.get("option_orders") or {}).get(pid)
            if order and eligible:
                entry["option_order"] = order
            answer = (rnd.get("answers") or {}).get(pid)
            entry["own_answer_status"] = rules.own_answer_status(state, pid, answer, eligible).value
            if answer:
                entry["selected_concept_id"] = answer["concept_id"]
                if "score_delta" in answer:
                    entry["score_delta"] = answer["score_delta"]
            entry["reaction_used"] = pid in (rnd.get("reactions") or {})
        muted = (state.get("mutes") or {}).get(uid)
        if muted:
            entry["muted_pids"] = muted  # reactions from these players are hidden for this viewer only
        settled = ((state.get("settlement") or {}).get("by_uid") or {}).get(uid)
        if settled:
            entry["settlement"] = settled
        private[uid] = entry
    for uid in state.get("spectators") or []:
        access.setdefault(uid, "spectator")
    return {"authoritative": state, "public": public, "player_private": private, "access": access}


def clone(state: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(state)

