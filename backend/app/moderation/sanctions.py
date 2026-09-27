"""User sanctions (spec §28.4, §29): rename-required, temporary suspension, permanent ban, reduced queue access and
ranked restriction.

Sanctions are immutable records in ``user_sanctions``; the user document carries a derived summary that request
paths enforce cheaply (``status``, ``suspended_until_ms``, ``rename_required``, ``queue_restricted_until_ms``,
``ranked_restricted_until_ms``). Lifting a sanction recomputes the summary from what is still active. Automatic
(risk-driven) sanctions are always temporary and reversible; a permanent ban needs a human decision.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from app.common.errors import ApiError, ErrorCode
from app.common.ids import new_uuid
from app.common.store.docstore import Query

log = logging.getLogger("oltivra.moderation")

FOREVER_MS = 2**62
PRESERVED_STATUSES = {"DELETION_PENDING", "DELETED"}


class SanctionKind(StrEnum):
    RENAME_REQUIRED = "RENAME_REQUIRED"
    QUEUE_RESTRICTION = "QUEUE_RESTRICTION"
    RANKED_RESTRICTION = "RANKED_RESTRICTION"
    SUSPEND = "SUSPEND"
    BAN = "BAN"


IRREVERSIBLE = {SanctionKind.BAN}
AUTOMATIC_ALLOWED = {SanctionKind.QUEUE_RESTRICTION, SanctionKind.RANKED_RESTRICTION}
REQUIRES_DURATION = {SanctionKind.QUEUE_RESTRICTION, SanctionKind.SUSPEND}


def sanction_path(sanction_id: str) -> str:
    return f"user_sanctions/{sanction_id}"


def ensure_can_play(user: dict[str, Any] | None, now_ms: int) -> None:
    """Queue/match entry gate: forced rename and reduced queue access (suspension is enforced per request)."""
    if not user:
        return
    if user.get("rename_required"):
        raise ApiError(ErrorCode.RENAME_REQUIRED)
    until = int(user.get("queue_restricted_until_ms") or 0)
    if until > now_ms:
        raise ApiError(ErrorCode.QUEUE_RESTRICTED, retry_after_s=max(1, (until - now_ms) // 1000),
                       detail={"available_at_ms": until})


def ranked_restricted(user: dict[str, Any] | None, now_ms: int) -> bool:
    return bool(user) and int(user.get("ranked_restricted_until_ms") or 0) > now_ms


def summarize(sanctions: list[dict[str, Any]], user: dict[str, Any], now_ms: int) -> dict[str, Any]:
    """Derive the enforcement summary on the user document from active sanctions."""
    active = [s for s in sanctions if s["state"] == "ACTIVE" and (s.get("ends_at_ms") or FOREVER_MS) > now_ms]
    kinds = {s["kind"] for s in active}

    def until(kind: SanctionKind) -> int | None:
        ends = [s.get("ends_at_ms") or FOREVER_MS for s in active if s["kind"] == kind]
        return max(ends) if ends else None

    status = user.get("status", "ACTIVE")
    if status not in PRESERVED_STATUSES:
        if SanctionKind.BAN in kinds:
            status = "BANNED"
        elif SanctionKind.SUSPEND in kinds:
            status = "SUSPENDED"
        else:
            status = "ACTIVE"
    renamed_at = int(user.get("username_changed_at_ms") or 0)
    # A rename sanction is satisfied by any username change made after it was issued.
    rename = any(s["kind"] == SanctionKind.RENAME_REQUIRED and s["created_at_ms"] > renamed_at for s in active)
    return {"status": status, "suspended_until_ms": until(SanctionKind.SUSPEND), "rename_required": rename,
            "queue_restricted_until_ms": until(SanctionKind.QUEUE_RESTRICTION),
            "ranked_restricted_until_ms": until(SanctionKind.RANKED_RESTRICTION)}


class SanctionService:
    def __init__(self, container) -> None:
        self._c = container

    async def list_for(self, uid: str) -> list[dict[str, Any]]:
        rows = await self._c.store.query(Query("user_sanctions").filter("uid", "==", uid))
        return sorted((r.data for r in rows), key=lambda s: -s["created_at_ms"])

    async def _recompute(self, uid: str) -> dict[str, Any]:
        c = self._c
        sanctions = await self.list_for(uid)
        now = c.clock.now_ms()

        def txn_fn(txn) -> dict[str, Any]:
            user = txn.get(f"users/{uid}")
            if not user:
                return {}
            summary = summarize(sanctions, user, now)
            txn.update(f"users/{uid}", {**summary, "updated_at_ms": now})
            return summary

        return await c.store.run_transaction(txn_fn)

    async def apply(self, uid: str, kind: SanctionKind, *, actor: str, reason_code: str, duration_ms: int | None,
                    source: str = "ADMIN", evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        c = self._c
        if uid.startswith("bot:"):
            raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "bots_are_managed_in_catalog"})
        if source != "ADMIN" and kind not in AUTOMATIC_ALLOWED:
            raise ApiError(ErrorCode.FORBIDDEN, detail={"reason": "human_decision_required"})
        if kind in REQUIRES_DURATION and not duration_ms:
            raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "duration_required"})
        if kind == SanctionKind.BAN:
            duration_ms = None  # permanent
        if not await c.store.get(f"users/{uid}"):
            raise ApiError(ErrorCode.NOT_FOUND)
        now = c.clock.now_ms()
        sanction = {"schema_version": 1, "sanction_id": new_uuid(), "uid": uid, "kind": kind.value,
                    "state": "ACTIVE", "source": source, "actor": actor, "reason_code": reason_code,
                    "created_at_ms": now, "ends_at_ms": now + duration_ms if duration_ms else None,
                    "reversible": kind not in IRREVERSIBLE, "evidence": evidence or {}}
        await c.store.create(sanction_path(sanction["sanction_id"]), sanction)
        summary = await self._recompute(uid)
        if kind in (SanctionKind.SUSPEND, SanctionKind.BAN, SanctionKind.QUEUE_RESTRICTION,
                    SanctionKind.RENAME_REQUIRED):
            await self._leave_queue(uid)
        await c.audit.record(actor=actor, action=f"SANCTION_{kind.value}", subject=f"user:{uid}",
                             reason_code=reason_code, reversible=kind not in IRREVERSIBLE,
                             detail={"sanction_id": sanction["sanction_id"], "source": source,
                                     "ends_at_ms": sanction["ends_at_ms"]})
        log.warning("sanction_applied", extra={"kind": kind.value, "source": source})
        return {**sanction, "summary": summary}

    async def lift(self, sanction_id: str, *, actor: str, reason_code: str) -> dict[str, Any]:
        c = self._c
        sanction = await c.store.get(sanction_path(sanction_id))
        if not sanction:
            raise ApiError(ErrorCode.NOT_FOUND)
        if not sanction.get("reversible", True):
            raise ApiError(ErrorCode.CONFLICT, detail={"reason": "irreversible_sanction"})
        if sanction["state"] != "ACTIVE":
            return {**sanction, "summary": await self._recompute(sanction["uid"])}
        now = c.clock.now_ms()
        await c.store.update(sanction_path(sanction_id), {"state": "LIFTED", "lifted_by": actor,
                                                          "lifted_at_ms": now, "lift_reason": reason_code})
        summary = await self._recompute(sanction["uid"])
        await c.audit.record(actor=actor, action="SANCTION_LIFT", subject=f"user:{sanction['uid']}",
                             reason_code=reason_code, detail={"sanction_id": sanction_id, "kind": sanction["kind"]})
        return {**sanction, "state": "LIFTED", "summary": summary}

    async def expire_due(self, limit: int = 500) -> int:
        """Scheduled: mark ended sanctions EXPIRED and refresh the enforcement summary."""
        c = self._c
        now = c.clock.now_ms()
        rows = await c.store.query(Query("user_sanctions").filter("state", "==", "ACTIVE")
                                   .filter("ends_at_ms", "<=", now).take(limit))
        uids = set()
        for row in rows:
            if row.data.get("ends_at_ms") is None:
                continue
            await c.store.update(row.path, {"state": "EXPIRED", "expired_at_ms": now})
            uids.add(row.data["uid"])
        for uid in uids:
            await self._recompute(uid)
        return len(uids)

    async def _leave_queue(self, uid: str) -> None:
        """Cancel a waiting ticket; an active match is allowed to finish and settle (spec §30.1 spirit)."""
        from app.accounts.runtime import runtime_path
        from app.matches.model import Mode

        runtime = await self._c.store.get(runtime_path(uid)) or {}
        if runtime.get("state") != "QUEUED" or not runtime.get("active_ticket_id"):
            return
        ticket = await self._c.store.get(f"matchmaking_tickets/{runtime['active_ticket_id']}") or {}
        try:
            await self._c.matchmaking.leave(uid, Mode(ticket.get("mode", "QUICK")))
        except ApiError:
            log.info("sanction_queue_leave_skipped")
