"""Block and player report (spec §6.1, §29)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from app.common.clock import Clock
from app.common.errors import ApiError, ErrorCode
from app.common.ids import new_uuid
from app.common.store.docstore import DocStore, Query


class PlayerReportReason(StrEnum):
    OFFENSIVE_USERNAME = "OFFENSIVE_USERNAME"
    IMPERSONATION = "IMPERSONATION"
    HARASSMENT = "HARASSMENT"
    SUSPECTED_CHEATING = "SUSPECTED_CHEATING"
    OTHER = "OTHER"


def block_path(blocker: str, blocked: str) -> str:
    return f"blocks/{blocker}_{blocked}"


class SafetyService:
    def __init__(self, store: DocStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    async def block(self, blocker: str, blocked: str) -> None:
        if blocker == blocked:
            raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "cannot_block_self"})
        now = self._clock.now_ms()
        await self._store.set(block_path(blocker, blocked), {
            "schema_version": 1, "blocker_uid": blocker, "blocked_uid": blocked, "created_at_ms": now,
        })
        # Pending friend requests in either direction are closed; the friendship edge is kept for audit but hidden.
        for sender, recipient in ((blocker, blocked), (blocked, blocker)):
            rows = await self._store.query(Query("friend_requests").filter("sender_uid", "==", sender)
                                           .filter("recipient_uid", "==", recipient).filter("state", "==", "PENDING"))
            for row in rows:
                await self._store.update(row.path, {"state": "CANCELLED_BY_BLOCK", "updated_at_ms": now})

    async def unblock(self, blocker: str, blocked: str) -> None:
        await self._store.delete(block_path(blocker, blocked))

    async def is_blocked_either_way(self, uid_a: str, uid_b: str) -> bool:
        docs = await self._store.get_many([block_path(uid_a, uid_b), block_path(uid_b, uid_a)])
        return any(docs)

    @staticmethod
    def blocked_either_way_in_txn(txn, uid_a: str, uid_b: str) -> bool:
        return any(txn.get_many([block_path(uid_a, uid_b), block_path(uid_b, uid_a)]))

    async def blocked_by_me(self, uid: str) -> list[str]:
        rows = await self._store.query(Query("blocks").filter("blocker_uid", "==", uid))
        return [r.data["blocked_uid"] for r in sorted(rows, key=lambda r: -r.data["created_at_ms"])]

    async def block_set(self, uid: str) -> set[str]:
        """Everyone ``uid`` blocked or was blocked by (used for matchmaking exclusion and reaction hiding)."""
        mine = await self._store.query(Query("blocks").filter("blocker_uid", "==", uid))
        theirs = await self._store.query(Query("blocks").filter("blocked_uid", "==", uid))
        return {r.data["blocked_uid"] for r in mine} | {r.data["blocker_uid"] for r in theirs}

    async def report_player(self, reporter: str, target: str, reason: PlayerReportReason,
                            context: dict[str, Any] | None = None) -> str:
        if reporter == target:
            raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "cannot_report_self"})
        report_id = new_uuid()
        await self._store.set(f"player_reports/{report_id}", {
            "schema_version": 1, "report_id": report_id, "reporter_uid": reporter, "target_uid": target,
            "reason": reason.value, "context": {k: v for k, v in (context or {}).items() if k in {"match_id"}},
            "status": "OPEN", "created_at_ms": self._clock.now_ms(),
        })
        return report_id
