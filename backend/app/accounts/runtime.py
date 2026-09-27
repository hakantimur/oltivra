"""Per-user Live Trivia runtime lock (spec §18.2).

Every queue/party/match/settlement/deletion transition changes ``user_runtime/{uid}`` inside the same
DocStore transaction as the business write, which prevents concurrent matches and out-of-order progression.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from app.common.errors import ApiError, ErrorCode


class RuntimeState(StrEnum):
    IDLE = "IDLE"
    QUEUED = "QUEUED"
    IN_PARTY = "IN_PARTY"
    MATCH_ACTIVE = "MATCH_ACTIVE"
    SETTLEMENT_PENDING = "SETTLEMENT_PENDING"
    DELETION_PENDING = "DELETION_PENDING"
    SUSPENDED = "SUSPENDED"


def runtime_path(uid: str) -> str:
    return f"user_runtime/{uid}"


def idle_runtime(uid: str, now_ms: int, lock_version: int = 0) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "uid": uid,
        "state": RuntimeState.IDLE.value,
        "active_ticket_id": None,
        "active_party_id": None,
        "active_match_id": None,
        "active_shard_id": None,
        "pending_settlement_match_id": None,
        "updated_at_ms": now_ms,
        "lock_version": lock_version,
    }


def current(doc: dict[str, Any] | None, uid: str, now_ms: int) -> dict[str, Any]:
    return dict(doc) if doc else idle_runtime(uid, now_ms)


def require_idle(runtime: dict[str, Any]) -> None:
    """A user may belong to only one waiting party, queue ticket, or active match (spec §6.2, §21.3)."""
    state = RuntimeState(runtime["state"])
    if state == RuntimeState.IDLE:
        return
    if state == RuntimeState.SETTLEMENT_PENDING:
        raise ApiError(ErrorCode.MATCH_SETTLEMENT_PENDING, retryable=True, retry_after_s=2)
    if state == RuntimeState.DELETION_PENDING:
        raise ApiError(ErrorCode.ACCOUNT_DELETION_PENDING)
    if state == RuntimeState.SUSPENDED:
        raise ApiError(ErrorCode.ACCOUNT_SUSPENDED)
    raise ApiError(ErrorCode.ACTIVE_RUNTIME_CONFLICT, detail=pointer(runtime))


def transition(runtime: dict[str, Any], state: RuntimeState, now_ms: int, **fields: Any) -> dict[str, Any]:
    updated = {**runtime, **fields, "state": state.value, "updated_at_ms": now_ms,
               "lock_version": int(runtime.get("lock_version", 0)) + 1}
    if state == RuntimeState.IDLE:
        updated.update(active_ticket_id=None, active_party_id=None, active_match_id=None, active_shard_id=None,
                       pending_settlement_match_id=None)
    return updated


def pointer(runtime: dict[str, Any]) -> dict[str, Any]:
    """Client-safe active queue/party/match pointer for bootstrap and conflict responses."""
    return {
        "state": runtime.get("state", RuntimeState.IDLE.value),
        "ticket_id": runtime.get("active_ticket_id"),
        "party_id": runtime.get("active_party_id"),
        "match_id": runtime.get("active_match_id") or runtime.get("pending_settlement_match_id"),
        "shard_id": runtime.get("active_shard_id"),
    }
