"""Canonical live match root vocabulary (spec §17, §24).

The authoritative branch is the only source of truth. Public and player-private projections are derived
from it by a pure function on every committed transition, so all three change atomically together.
Values follow RTDB semantics: empty containers and ``None`` disappear, so readers use ``.get(x) or {}``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

SCHEMA_VERSION = 1
MAX_PUBLIC_EVENTS = 40
MAX_AUDIT_ENTRIES = 300
DISPLAY_POSITIONS = ("A", "B", "C", "D")


class MatchState(StrEnum):
    CREATED = "CREATED"
    WAITING_FOR_PLAYERS = "WAITING_FOR_PLAYERS"
    PREPARING = "PREPARING"
    ROUND_LOADING = "ROUND_LOADING"
    ROUND_ACTIVE = "ROUND_ACTIVE"
    ROUND_REVEAL = "ROUND_REVEAL"
    ROUND_RESOLVE = "ROUND_RESOLVE"
    NEXT_ROUND = "NEXT_ROUND"
    FINISHED_PENDING_SETTLEMENT = "FINISHED_PENDING_SETTLEMENT"
    FINISHED = "FINISHED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


LIVE_STATES = {MatchState.ROUND_LOADING, MatchState.ROUND_ACTIVE, MatchState.ROUND_REVEAL, MatchState.ROUND_RESOLVE,
               MatchState.NEXT_ROUND, MatchState.PREPARING}
TERMINAL_STATES = {MatchState.FINISHED, MatchState.CANCELLED, MatchState.EXPIRED}


class Mode(StrEnum):
    QUICK = "QUICK"
    SURVIVAL = "SURVIVAL"


class Phase(StrEnum):
    QUICK_NORMAL = "QUICK_NORMAL"
    QUICK_SUDDEN_DEATH = "QUICK_SUDDEN_DEATH"
    SURVIVAL_NORMAL = "SURVIVAL_NORMAL"
    SURVIVAL_RESCUE = "SURVIVAL_RESCUE"
    SURVIVAL_TIEBREAK = "SURVIVAL_TIEBREAK"


class RoundKind(StrEnum):
    NORMAL = "NORMAL"
    SUDDEN_DEATH = "SUDDEN_DEATH"
    RESCUE = "RESCUE"
    TIEBREAK = "TIEBREAK"


class AnswerStatus(StrEnum):
    NOT_ANSWERED = "NOT_ANSWERED"
    ANSWERED_WRONG = "ANSWERED_WRONG"
    ANSWERED_CORRECT = "ANSWERED_CORRECT"
    LOCKED = "LOCKED"
    INELIGIBLE = "INELIGIBLE"


class SurvivalStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SURVIVED = "SURVIVED"
    PROTECTED = "PROTECTED"
    ELIMINATED = "ELIMINATED"
    WINNER = "WINNER"


class EventType(StrEnum):
    WRONG = "WRONG"
    WIN = "WIN"
    REACTION = "REACTION"
    ELIMINATED = "ELIMINATED"
    SURVIVED = "SURVIVED"
    RESCUE = "RESCUE"
    TIEBREAK = "TIEBREAK"
    SUDDEN_DEATH = "SUDDEN_DEATH"
    LEFT = "LEFT"
    NO_WINNER = "NO_WINNER"


@dataclass(frozen=True)
class Effect:
    """Side effect executed only after the canonical transaction commits (spec §19)."""

    kind: str  # a TaskKind value, or SIGN_MEDIA / START_SETTLEMENT / REFILL_QUESTIONS
    eta_ms: int
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepResult:
    changed: bool = False
    effects: list[Effect] = field(default_factory=list)
    outcome: dict[str, Any] = field(default_factory=dict)


def participants(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return state.get("participants") or {}


def humans(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {pid: p for pid, p in participants(state).items() if p.get("kind") == "HUMAN"}


def pid_for_uid(state: dict[str, Any], uid: str) -> str | None:
    for pid, p in participants(state).items():
        if p.get("uid") == uid:
            return pid
    return None


def current_round(state: dict[str, Any]) -> dict[str, Any]:
    return state.get("round") or {}


def append_event(state: dict[str, Any], now_ms: int, event_type: EventType, pid: str | None = None,
                 value: Any = None, **extra: Any) -> None:
    seq = int(state.get("event_seq", 0)) + 1
    state["event_seq"] = seq
    event: dict[str, Any] = {"seq": seq, "type": event_type.value, "at_ms": now_ms,
                             "round_id": current_round(state).get("round_id", "-")}
    if pid is not None:
        event["pid"] = pid
    if value is not None:
        event["value"] = value
    event.update({k: v for k, v in extra.items() if v is not None})
    events = list(state.get("events") or [])
    events.append(event)
    state["events"] = events[-MAX_PUBLIC_EVENTS:]


def audit(state: dict[str, Any], now_ms: int, action: str, source: str) -> None:
    log = list((state.get("audit") or {}).get("log") or [])
    log.append({"at_ms": now_ms, "state": state.get("state"), "phase": state.get("match_phase"),
                "state_version": state.get("state_version"), "action": action, "source": source})
    state.setdefault("audit", {})
    state["audit"] = {**(state.get("audit") or {}), "log": log[-MAX_AUDIT_ENTRIES:]}


def bump(state: dict[str, Any], now_ms: int, action: str, source: str) -> None:
    state["state_version"] = int(state.get("state_version", 0)) + 1
    audit(state, now_ms, action, source)
