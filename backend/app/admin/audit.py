"""Admin/moderation audit log (spec §29): actor, reason code, timestamp, reversible/irreversible status."""

from __future__ import annotations

from typing import Any

from app.common.ids import new_uuid
from app.common.store.docstore import Query


class AuditLog:
    def __init__(self, store, clock) -> None:
        self._store = store
        self._clock = clock

    async def record(self, *, actor: str, action: str, subject: str, reason_code: str = "", reversible: bool = True,
                     detail: dict[str, Any] | None = None) -> str:
        entry_id = new_uuid()
        await self._store.set(f"audit_log/{entry_id}", {
            "schema_version": 1, "id": entry_id, "actor": actor, "action": action, "subject": subject,
            "reason_code": reason_code, "reversible": reversible, "detail": detail or {},
            "at_ms": self._clock.now_ms()})
        return entry_id

    async def list(self, *, subject: str | None = None, actor: str | None = None, limit: int = 50) -> list[dict]:
        query = Query("audit_log")
        if subject:
            query = query.filter("subject", "==", subject)
        if actor:
            query = query.filter("actor", "==", actor)
        rows = await self._store.query(query.order("at_ms", "desc").take(limit))
        return [r.data for r in rows]
