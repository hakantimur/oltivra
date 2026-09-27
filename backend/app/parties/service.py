"""Friend Challenge parties and rematch (spec §6.2, §6.3, §18.9).

Both are temporary human rosters that reuse the standard engines: a challenge is a Quick Battle party of
2–4 accepted humans (60 s invitation, auto-start at expiry with >= 2), a rematch is a 10-second window
after settlement for the prior match's humans. Missing slots are filled with bots. A user belongs to only
one waiting party, queue ticket or active match (``user_runtime``).
"""

from __future__ import annotations

import logging
from typing import Any

from app.accounts.runtime import RuntimeState, current, require_idle, runtime_path, transition
from app.common.clock import ms_to_datetime
from app.common.errors import ApiError, ErrorCode
from app.common.ids import random_token
from app.common.tasks import TaskKind, TaskRequest
from app.matches.factory import HumanSeat
from app.matches.model import Mode
from app.matches.shards import shard_for
from app.moderation.safety import SafetyService
from app.notifications.service import NotificationKind
from app.profiles.service import user_path
from app.questions.selector import InsufficientInventory

log = logging.getLogger("oltivra.parties")

PARTY_TTL_MS = 60_000
MAX_INVITES = 3
MAX_MEMBERS = 4
OPEN_STATES = ("WAITING", "READY")


def party_path(party_id: str) -> str:
    return f"parties/{party_id}"


def invite_path(token: str) -> str:
    return f"party_invites/{token}"


def rematch_party_id(match_id: str) -> str:
    return f"rm_{match_id}"


class PartyService:
    def __init__(self, container) -> None:
        self._c = container

    # ------------------------------------------------------------------------------------------ views
    async def _card(self, uid: str) -> dict[str, Any]:
        user = await self._c.store.get(user_path(uid)) or {}
        return {"public_id": user.get("public_id"), "username": user.get("username_display"),
                "avatar_id": user.get("avatar_id"), "frame_id": user.get("frame_id", "frame_none")}

    async def view(self, party: dict[str, Any], uid: str | None = None) -> dict[str, Any]:
        accepted = list(party.get("accepted_uids") or [])
        invited = list(party.get("invited_uids") or [])
        members = []
        for member in dict.fromkeys([party["host_uid"], *invited, *accepted]):
            card = await self._card(member)
            card["status"] = "ACCEPTED" if member in accepted else "INVITED"
            card["is_host"] = member == party["host_uid"]
            card["is_you"] = member == uid
            members.append(card)
        out = {"schema_version": 1, "party_id": party["party_id"], "kind": party["kind"], "mode": party["mode"],
               "question_language": party["question_language"], "state": party["state"],
               "expires_at_ms": party["expires_at_ms"], "members": members,
               "min_humans": party.get("min_humans", 2), "match_id": party.get("match_id")}
        if party.get("match_id"):
            idx = await self._c.store.get(f"match_index/{party['match_id']}") or {}
            shard = idx.get("rtdb_shard_id")
            out["match"] = {"match_id": party["match_id"], "rtdb_shard_id": shard,
                            "rtdb_url": self._c.settings.shard_url(shard) if shard else None}
        return out

    async def get(self, uid: str, party_id: str) -> dict[str, Any]:
        party = await self._c.store.get(party_path(party_id))
        if not party or uid not in {party["host_uid"], *(party.get("invited_uids") or [])}:
            raise ApiError(ErrorCode.NOT_FOUND)
        return await self.view(party, uid)

    async def my_invites(self, uid: str) -> dict[str, Any]:
        from app.common.store.docstore import Query

        now = self._c.clock.now_ms()
        rows = await self._c.store.query(Query("party_invites").filter("uid", "==", uid)
                                         .filter("state", "==", "PENDING"))
        invites = []
        for row in rows:
            if row.data["expires_at_ms"] <= now:
                continue
            party = await self._c.store.get(party_path(row.data["party_id"]))
            if not party or party["state"] not in OPEN_STATES:
                continue
            invites.append({"invite_token": row.id, "party_id": party["party_id"], "host": await self._card(
                party["host_uid"]), "question_language": party["question_language"], "mode": party["mode"],
                "expires_at_ms": party["expires_at_ms"]})
        return {"schema_version": 1, "invites": invites}

    def _schedule_expiry(self, party_id: str, kind: TaskKind, eta_ms: int):
        shard = shard_for(self._c.keys, party_id, self._c.settings.shard_ids)
        return self._c.tasks.schedule(TaskRequest(kind, shard, eta_ms, {"party_id": party_id}, (party_id,)))

    # ------------------------------------------------------------------------------------------ challenge
    async def _ensure_can_play(self, uid: str) -> None:
        from app.moderation.sanctions import ensure_can_play

        ensure_can_play(await self._c.store.get(f"users/{uid}"), self._c.clock.now_ms())

    async def create_challenge(self, host_uid: str, friend_public_ids: list[str], language: str) -> dict[str, Any]:
        c = self._c
        config = await c.config.get()
        if not config.features.new_matches_enabled:
            raise ApiError(ErrorCode.CAPACITY_UNAVAILABLE, retry_after_s=30)
        if language not in config.features.competitive_languages:
            raise ApiError(ErrorCode.FEATURE_DISABLED, detail={"feature": "question_language"})
        await self._ensure_can_play(host_uid)
        unique = list(dict.fromkeys(friend_public_ids))
        if not 1 <= len(unique) <= MAX_INVITES:
            raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "invite_count"})
        invitees = []
        for public_id in unique:
            friend = await c.profiles.uid_for_public_id(public_id)
            if friend == host_uid or not await c.friends.are_friends(host_uid, friend):
                raise ApiError(ErrorCode.FORBIDDEN, detail={"reason": "not_friends"})
            invitees.append(friend)
        now = c.clock.now_ms()
        party_id = random_token(18)
        tokens = {uid: random_token(24) for uid in invitees}
        party = {
            "schema_version": 1, "party_id": party_id, "kind": "CHALLENGE", "mode": Mode.QUICK.value,
            "question_language": language, "state": "WAITING", "host_uid": host_uid, "invited_uids": invitees,
            "accepted_uids": [host_uid], "min_humans": 2, "source": "CHALLENGE", "created_at_ms": now,
            "expires_at_ms": now + PARTY_TTL_MS, "expires_at": ms_to_datetime(now + PARTY_TTL_MS),
            "match_id": None}

        def txn_fn(txn) -> None:
            runtime = current(txn.get(runtime_path(host_uid)), host_uid, now)
            require_idle(runtime)
            txn.create(party_path(party_id), party)
            for uid, token in tokens.items():
                txn.create(invite_path(token), {"schema_version": 1, "party_id": party_id, "uid": uid,
                                                "state": "PENDING", "expires_at_ms": party["expires_at_ms"],
                                                "created_at_ms": now})
            txn.set(runtime_path(host_uid), transition(runtime, RuntimeState.IN_PARTY, now,
                                                       active_party_id=party_id))

        await c.store.run_transaction(txn_fn)
        await self._schedule_expiry(party_id, TaskKind.PARTY_EXPIRY, party["expires_at_ms"])
        host = await c.store.get(user_path(host_uid)) or {}
        for uid, token in tokens.items():
            # The deep link carries only the opaque invite token (spec §6.2).
            await c.notifications.notify(uid, NotificationKind.FRIEND_CHALLENGE, sender_uid=host_uid,
                                         data={"invite_token": token, "party_id": party_id},
                                         body_args=[host.get("username_display") or ""])
        return await self.view(party, host_uid)

    async def accept_invite(self, uid: str, token: str, accepted_language: str) -> dict[str, Any]:
        c = self._c
        invite = await c.store.get(invite_path(token))
        now = c.clock.now_ms()
        if not invite or invite.get("uid") != uid:
            raise ApiError(ErrorCode.NOT_FOUND)
        await self._ensure_can_play(uid)
        party = await c.store.get(party_path(invite["party_id"]))
        if not party:
            raise ApiError(ErrorCode.NOT_FOUND)
        if invite.get("state") == "ACCEPTED" and uid in (party.get("accepted_uids") or []):
            return await self.view(party, uid)
        if now >= invite["expires_at_ms"] or party["state"] not in OPEN_STATES:
            raise ApiError(ErrorCode.PARTY_EXPIRED)
        if accepted_language != party["question_language"]:
            # Invitees must explicitly accept the host's question language (spec §6.2).
            raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "language_not_accepted",
                                                              "question_language": party["question_language"]})

        def txn_fn(txn) -> dict[str, Any]:
            fresh_invite, fresh, runtime_doc = txn.get_many([invite_path(token), party_path(party["party_id"]),
                                                             runtime_path(uid)])
            accepted = list(fresh.get("accepted_uids") or [])
            blocked = any(SafetyService.blocked_either_way_in_txn(txn, uid, other) for other in accepted)
            if fresh["state"] not in OPEN_STATES or fresh_invite.get("state") != "PENDING":
                raise ApiError(ErrorCode.PARTY_EXPIRED)
            if len(accepted) >= MAX_MEMBERS:
                raise ApiError(ErrorCode.PARTY_FULL)
            if blocked:
                raise ApiError(ErrorCode.BLOCKED)
            runtime = current(runtime_doc, uid, now)
            require_idle(runtime)
            accepted.append(uid)
            state = "READY" if len(accepted) >= fresh.get("min_humans", 2) else "WAITING"
            txn.update(party_path(fresh["party_id"]), {"accepted_uids": accepted, "state": state,
                                                        "updated_at_ms": now})
            txn.update(invite_path(token), {"state": "ACCEPTED", "updated_at_ms": now})
            txn.set(runtime_path(uid), transition(runtime, RuntimeState.IN_PARTY, now,
                                                  active_party_id=fresh["party_id"]))
            return {**fresh, "accepted_uids": accepted, "state": state}

        updated = await c.store.run_transaction(txn_fn)
        me = await c.store.get(user_path(uid)) or {}
        await c.notifications.notify(party["host_uid"], NotificationKind.CHALLENGE_ACCEPTED, sender_uid=uid,
                                     data={"party_id": party["party_id"]},
                                     body_args=[me.get("username_display") or ""])
        return await self.view(updated, uid)

    async def decline_invite(self, uid: str, token: str) -> dict[str, Any]:
        invite = await self._c.store.get(invite_path(token))
        if not invite or invite.get("uid") != uid:
            raise ApiError(ErrorCode.NOT_FOUND)
        if invite.get("state") == "PENDING":
            await self._c.store.update(invite_path(token), {"state": "DECLINED",
                                                            "updated_at_ms": self._c.clock.now_ms()})
        return {"schema_version": 1, "state": "DECLINED"}

    # ------------------------------------------------------------------------------------------ leave / start
    async def leave(self, uid: str, party_id: str) -> dict[str, Any]:
        c = self._c
        now = c.clock.now_ms()

        def txn_fn(txn) -> dict[str, Any]:
            party = txn.get(party_path(party_id))
            if not party or uid not in {party["host_uid"], *(party.get("invited_uids") or [])}:
                raise ApiError(ErrorCode.NOT_FOUND)
            accepted = list(party.get("accepted_uids") or [])
            runtimes = dict(zip(accepted, txn.get_many([runtime_path(u) for u in accepted]), strict=True))
            if party["state"] not in OPEN_STATES:
                return party  # matched/cancelled: nothing to leave
            if uid not in accepted:
                return party
            leaving = accepted if uid == party["host_uid"] else [uid]
            remaining = [u for u in accepted if u not in leaving]
            reason = None
            if uid == party["host_uid"]:
                state, reason = "CANCELLED", "HOST_LEFT"
            elif len(remaining) < 2:
                # Fewer than two humans remain: the party cancels with no progression change (spec §6.2).
                state, reason = "CANCELLED", "INSUFFICIENT_HUMANS"
            else:
                state = "READY" if len(remaining) >= party.get("min_humans", 2) else "WAITING"
            if state == "CANCELLED":
                leaving = accepted
            for member in leaving:
                runtime = current(runtimes[member], member, now)
                if runtime.get("active_party_id") == party_id:
                    txn.set(runtime_path(member), transition(runtime, RuntimeState.IDLE, now))
            txn.update(party_path(party_id), {"accepted_uids": remaining, "state": state, "updated_at_ms": now,
                                              **({"cancel_reason": reason} if reason else {})})
            return {**party, "accepted_uids": remaining, "state": state}

        party = await c.store.run_transaction(txn_fn)
        return await self.view(party, uid)

    async def start(self, uid: str, party_id: str) -> dict[str, Any]:
        party = await self._c.store.get(party_path(party_id))
        if not party or party["host_uid"] != uid:
            raise ApiError(ErrorCode.FORBIDDEN, detail={"reason": "host_only"})
        if party["state"] == "MATCHED":
            return await self.view(party, uid)
        if party["state"] != "READY":
            raise ApiError(ErrorCode.CONFLICT, detail={"reason": "not_enough_players",
                                                        "min_humans": party.get("min_humans", 2)})
        await self._launch(party_id)
        return await self.view(await self._c.store.get(party_path(party_id)), uid)

    async def expire(self, party_id: str) -> dict[str, Any]:
        """PARTY_EXPIRY / REMATCH_EXPIRY: auto-start with enough humans, otherwise expire (no progression)."""
        c = self._c
        party = await c.store.get(party_path(party_id))
        if not party or party["state"] not in OPEN_STATES:
            return {"state": (party or {}).get("state")}
        if c.clock.now_ms() < party["expires_at_ms"]:
            return {"state": party["state"], "early": True}
        if len(party.get("accepted_uids") or []) >= party.get("min_humans", 2):
            await self._launch(party_id)
        else:
            await self._close(party_id, "EXPIRED")
        return {"state": (await c.store.get(party_path(party_id)))["state"]}

    async def _close(self, party_id: str, state: str) -> None:
        now = self._c.clock.now_ms()

        def txn_fn(txn) -> None:
            party = txn.get(party_path(party_id))
            if not party or party["state"] not in (*OPEN_STATES, "STARTING"):
                return
            accepted = list(party.get("accepted_uids") or [])
            runtimes = txn.get_many([runtime_path(u) for u in accepted])
            for member, doc in zip(accepted, runtimes, strict=True):
                runtime = current(doc, member, now)
                if runtime.get("active_party_id") == party_id:
                    txn.set(runtime_path(member), transition(runtime, RuntimeState.IDLE, now))
            txn.update(party_path(party_id), {"state": state, "updated_at_ms": now})

        await self._c.store.run_transaction(txn_fn)

    async def _launch(self, party_id: str) -> str | None:
        c = self._c
        now = c.clock.now_ms()

        def begin(txn) -> dict[str, Any] | None:
            party = txn.get(party_path(party_id))
            if not party or party["state"] not in OPEN_STATES:
                return None
            txn.update(party_path(party_id), {"state": "STARTING", "updated_at_ms": now})
            return party

        party = await c.store.run_transaction(begin)
        if not party:
            return None
        accepted = list(party["accepted_uids"])
        users = await c.store.get_many([user_path(u) for u in accepted])
        seats = [HumanSeat(uid=u, username=d["username_display"], avatar_id=d["avatar_id"],
                           frame_id=d.get("frame_id", "frame_none"), mmr=int(d.get("mmr", 1000)))
                 for u, d in zip(accepted, users, strict=True) if d]
        try:
            prepared = await c.match_factory.prepare(mode=Mode(party["mode"]), language=party["question_language"],
                                                     humans=seats, source=party.get("source", "CHALLENGE"))
        except (ApiError, InsufficientInventory):
            await c.store.update(party_path(party_id), {"state": "READY", "updated_at_ms": c.clock.now_ms()})
            raise
        prepared.extra = {"party_id": party_id}
        minimum = party.get("min_humans", 2)

        def claim(txn) -> str:
            fresh = txn.get(party_path(party_id))
            runtimes = txn.get_many([runtime_path(s.uid) for s in prepared.humans])
            if not fresh or fresh["state"] != "STARTING":
                return "GONE"
            valid = [s.uid for s, doc in zip(prepared.humans, runtimes, strict=True)
                     if current(doc, s.uid, now)["state"] == RuntimeState.IN_PARTY
                     and current(doc, s.uid, now).get("active_party_id") == party_id]
            if len(valid) < minimum:
                return "CANCEL"
            if len(valid) != len(prepared.humans):
                return "RETRY"
            for seat, doc in zip(prepared.humans, runtimes, strict=True):
                runtime = current(doc, seat.uid, now)
                txn.set(runtime_path(seat.uid), transition(runtime, RuntimeState.MATCH_ACTIVE, now,
                                                           active_party_id=None, active_match_id=prepared.match_id,
                                                           active_shard_id=prepared.shard_id))
            txn.update(party_path(party_id), {"state": "MATCHED", "match_id": prepared.match_id,
                                              "updated_at_ms": now})
            c.match_factory.write_index_in_txn(txn, prepared, now)
            return "OK"

        outcome = await c.store.run_transaction(claim)
        if outcome == "OK":
            await c.match_factory.launch(prepared)
            return prepared.match_id
        if outcome == "CANCEL":
            await self._close(party_id, "CANCELLED")
        elif outcome == "RETRY":
            await c.store.update(party_path(party_id), {"state": "READY", "updated_at_ms": now})
            return await self._launch(party_id)
        return None

    # ------------------------------------------------------------------------------------------ rematch
    async def request_rematch(self, uid: str, match_id: str) -> dict[str, Any]:
        """Create or join the 10-second rematch window of a settled match (spec §6.3)."""
        c = self._c
        idx = await c.store.get(f"match_index/{match_id}")
        if not idx or uid not in (idx.get("participant_uids") or []):
            raise ApiError(ErrorCode.NOT_MATCH_PARTICIPANT)
        await self._ensure_can_play(uid)
        ledger = await c.store.get(f"settlement_ledgers/{match_id}")
        if not ledger or ledger.get("status") != "SETTLED":
            # Exposure history must be committed before a rematch selects questions.
            raise ApiError(ErrorCode.MATCH_SETTLEMENT_PENDING, retryable=True, retry_after_s=1)
        config = await c.config.get()
        window_ends = int(ledger["completed_at_ms"]) + config.quick.rematch_window_ms
        now = c.clock.now_ms()
        party_id = rematch_party_id(match_id)
        humans = list(idx["participant_uids"])
        # A rematch of a public match keeps public ranked rules; a friend challenge rematch stays unranked.
        source = "REMATCH" if idx.get("source", "PUBLIC") in ("PUBLIC", "REMATCH") else "CHALLENGE"

        def txn_fn(txn) -> tuple[dict[str, Any], bool]:
            party, runtime_doc = txn.get_many([party_path(party_id), runtime_path(uid)])
            runtime = current(runtime_doc, uid, now)
            if party and uid in (party.get("accepted_uids") or []):
                return party, False
            if now >= window_ends or (party and party["state"] not in OPEN_STATES):
                raise ApiError(ErrorCode.PARTY_EXPIRED)
            require_idle(runtime)
            created = party is None
            if created:
                party = {"schema_version": 1, "party_id": party_id, "kind": "REMATCH", "mode": idx["mode"],
                         "question_language": idx.get("language", "en"), "state": "READY", "host_uid": uid,
                         "invited_uids": humans, "accepted_uids": [uid], "min_humans": 1, "source": source,
                         "prior_match_id": match_id, "created_at_ms": now, "expires_at_ms": window_ends,
                         "expires_at": ms_to_datetime(window_ends), "match_id": None}
                txn.create(party_path(party_id), party)
            else:
                party = {**party, "accepted_uids": [*party["accepted_uids"], uid]}
                txn.update(party_path(party_id), {"accepted_uids": party["accepted_uids"], "updated_at_ms": now})
            txn.set(runtime_path(uid), transition(runtime, RuntimeState.IN_PARTY, now, active_party_id=party_id))
            return party, created

        party, created = await c.store.run_transaction(txn_fn)
        if created:
            await self._schedule_expiry(party_id, TaskKind.REMATCH_EXPIRY, window_ends)
        if set(party.get("accepted_uids") or []) >= set(humans) and party["state"] in OPEN_STATES:
            await self._launch(party_id)  # everyone accepted: no one waits for the window to close
            party = await c.store.get(party_path(party_id))
        return await self.view(party, uid)

    async def accept_rematch(self, uid: str, party_id: str) -> dict[str, Any]:
        if not party_id.startswith("rm_"):
            raise ApiError(ErrorCode.NOT_FOUND)
        return await self.request_rematch(uid, party_id.removeprefix("rm_"))
