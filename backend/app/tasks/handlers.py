"""Registers task handlers from feature modules.

Every live-round task calls the same idempotent resolver; task dispatch time is never an authoritative
answer or bot timestamp (spec §20.1). Duplicate or late tasks are safe no-ops.
"""

from __future__ import annotations

from typing import Any

from app.common.errors import ApiError, ErrorCode
from app.common.tasks import TaskKind
from app.tasks.dispatch import task_handler


def _ids(body: dict[str, Any]) -> tuple[str, str]:
    match_id, shard_id = body.get("match_id"), body.get("rtdb_shard_id")
    if not match_id or not shard_id:
        raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "missing_match_or_shard"})
    return match_id, shard_id


@task_handler(TaskKind.ROUND_START, TaskKind.ROUND_RECOVERY, TaskKind.ROUND_ADVANCE, TaskKind.BOT_WINNER)
async def resolve_round(container, body: dict[str, Any]) -> dict[str, Any]:
    match_id, shard_id = _ids(body)
    try:
        return await container.matches.resolve(match_id, shard_id, body["task_kind"])
    except ApiError as exc:
        if exc.code == ErrorCode.MATCH_NOT_FOUND:
            return {"changed": False, "reason": "gone"}  # cleaned up already: harmless
        raise


@task_handler(TaskKind.SETTLEMENT)
async def settle(container, body: dict[str, Any]) -> dict[str, Any]:
    match_id, shard_id = _ids(body)
    return await container.settlement.run(match_id, shard_id)


@task_handler(TaskKind.CLEANUP)
async def cleanup(container, body: dict[str, Any]) -> dict[str, Any]:
    match_id, shard_id = _ids(body)
    return await container.settlement.cleanup(match_id, shard_id)
