"""Shared Synova account deletion (spec §2.2, §30.1).

Deletion is global across participating products. A user in an active match is marked DELETION_PENDING and
the match is allowed to settle first; the settlement worker then completes the deletion. No live
authoritative match is ever orphaned.
"""

from __future__ import annotations

import logging
from typing import Any

from app.accounts.runtime import RuntimeState, current, runtime_path, transition
from app.auth.admin import AuthAdmin
from app.auth.verifiers import VerifiedToken
from app.common.clock import Clock
from app.common.errors import ApiError, ErrorCode
from app.common.keys import Keyring
from app.common.store.docstore import DocStore, Query
from app.profiles.service import USERNAME_RESERVATION_MS, registry_path, user_path

log = logging.getLogger("oltivra.accounts")

REAUTH_WINDOW_S = 300


class DeletionService:
    def __init__(self, store: DocStore, clock: Clock, keys: Keyring, auth_admin: AuthAdmin) -> None:
        self._store = store
        self._clock = clock
        self._keys = keys
        self._auth_admin = auth_admin

    def anon_id(self, uid: str) -> str:
        return "deleted_" + self._keys.username_hash.hexdigest(f"deleted:{uid}")[:16]

    async def request(self, uid: str, token: VerifiedToken) -> dict[str, Any]:
        now = self._clock.now_ms()
        if now // 1000 - token.auth_time_s > REAUTH_WINDOW_S:
            raise ApiError(ErrorCode.UNAUTHENTICATED, detail={"reason": "recent_login_required"})

        def txn_fn(txn) -> dict[str, Any]:
            user, runtime_doc, request = txn.get_many([user_path(uid), runtime_path(uid), f"deletion_requests/{uid}"])
            runtime = current(runtime_doc, uid, now)
            ticket = party = None
            if runtime.get("active_ticket_id"):
                ticket = txn.get(f"matchmaking_tickets/{runtime['active_ticket_id']}")
            if runtime.get("active_party_id"):
                party = txn.get(f"parties/{runtime['active_party_id']}")
            if request and request.get("status") in ("PENDING_MATCH", "PROCESSING", "COMPLETED"):
                return request
            state = RuntimeState(runtime["state"])
            in_match = state in (RuntimeState.MATCH_ACTIVE, RuntimeState.SETTLEMENT_PENDING)
            if ticket and ticket.get("state") == "QUEUED":
                txn.update(f"matchmaking_tickets/{ticket['ticket_id']}", {"state": "CANCELLED",
                                                                           "updated_at_ms": now})
            if party and party.get("state") in ("WAITING", "READY"):
                if party.get("host_uid") == uid:
                    txn.update(f"parties/{party['party_id']}", {"state": "CANCELLED", "updated_at_ms": now,
                                                                 "cancel_reason": "HOST_LEFT"})
                else:
                    txn.update(f"parties/{party['party_id']}", {
                        "accepted_uids": [u for u in party.get("accepted_uids", []) if u != uid],
                        "invited_uids": [u for u in party.get("invited_uids", []) if u != uid],
                        "updated_at_ms": now})
            status = "PENDING_MATCH" if in_match else "PROCESSING"
            doc = {"schema_version": 1, "uid": uid, "status": status, "requested_at_ms": now}
            txn.set(f"deletion_requests/{uid}", doc)
            if user:
                txn.update(user_path(uid), {"status": "DELETION_PENDING"})
            if in_match:
                txn.set(runtime_path(uid), {**runtime, "deletion_requested": True, "updated_at_ms": now})
            else:
                txn.set(runtime_path(uid), transition(runtime, RuntimeState.DELETION_PENDING, now))
            return doc

        doc = await self._store.run_transaction(txn_fn)
        if doc["status"] == "PROCESSING":
            await self.complete(uid)
            doc = {**doc, "status": "COMPLETED"}
        return {"schema_version": 1, "status": doc["status"]}

    async def complete(self, uid: str) -> None:
        """Idempotent erasure/anonymisation. Safe to retry from the settlement worker."""
        now = self._clock.now_ms()
        request = await self._store.get(f"deletion_requests/{uid}")
        if request and request.get("status") == "COMPLETED":
            return
        user = await self._store.get(user_path(uid)) or {}
        anon = self.anon_id(uid)
        await self._store.set(f"deletion_requests/{uid}", {"schema_version": 1, "uid": uid, "status": "PROCESSING",
                                                           "requested_at_ms": (request or {}).get("requested_at_ms",
                                                                                                  now)})
        # 1. Relationships and social records.
        for collection, fields in (("friend_requests", ("sender_uid", "recipient_uid")),
                                   ("blocks", ("blocker_uid", "blocked_uid")),
                                   ("device_tokens", ("uid",)),
                                   ("user_missions", ("uid",)),
                                   ("weekly_user_stats", ("uid",)),
                                   ("synova_items", ("uid",))):
            for field in fields:
                for row in await self._store.query(Query(collection).filter(field, "==", uid)):
                    await self._store.delete(row.path)
        for row in await self._store.query(Query("friendships").filter("member_uids", "array_contains", uid)):
            await self._store.delete(row.path)
        # 2. Historical matches keep aggregate stats with pseudonymous participants.
        for row in await self._store.query(Query("match_history").filter("participant_uids", "array_contains", uid)):
            participants = [{**p, "uid_or_bot_id": anon} if p.get("uid_or_bot_id") == uid else p
                            for p in row.data.get("participants", [])]
            await self._store.update(row.path, {
                "participant_uids": [anon if u == uid else u for u in row.data.get("participant_uids", [])],
                "participants": participants,
            })
        for row in await self._store.query(Query("purchase_transactions").filter("uid", "==", uid)):
            await self._store.update(row.path, {"uid": anon})
        for row in await self._store.query(Query("player_reports").filter("reporter_uid", "==", uid)):
            await self._store.update(row.path, {"reporter_uid": anon})
        # 3. Personal profile, private settings, runtime, exposure, entitlements.
        public_id = user.get("public_id")
        for path in (f"public_profiles/{public_id}" if public_id else None,
                     f"public_ids/{public_id}" if public_id else None,
                     f"user_recent_questions/{uid}", f"purchase_entitlements/{uid}", runtime_path(uid),
                     user_path(uid)):
            if path:
                await self._store.delete(path)
        # 4. Minimal hashed username reservation for 30 days (spec §30.1 step 8).
        if user.get("username_normalized"):
            await self._store.set(registry_path(user["username_normalized"]), {
                "schema_version": 1, "state": "RESERVED", "uid": None,
                "reserved_for_uid": None, "reserved_for_hash": anon,
                "reserved_until_ms": now + USERNAME_RESERVATION_MS, "updated_at_ms": now,
            })
        # 5. Global Firebase Auth identity last, so a retry can still find the records above.
        await self._auth_admin.delete_user(uid)
        await self._store.set(f"audit_log/deletion_{anon}", {
            "schema_version": 1, "action": "ACCOUNT_DELETED", "actor": "user", "subject": anon, "at_ms": now,
            "irreversible": True,
        })
        await self._store.set(f"deletion_requests/{uid}", {"schema_version": 1, "uid": uid, "status": "COMPLETED",
                                                           "completed_at_ms": now})
        log.info("account deleted", extra={"uid_ref": anon})
