"""Friends, requests and username search (spec §6.1).

Requests are directional until accepted, then a canonical friendship edge exists. A block prevents new
requests, challenges and social notifications in both directions; an existing friendship stays stored for
audit but is hidden and non-interactive while blocked. Search returns only the minimum safe profile.
"""

from __future__ import annotations

from typing import Any

from app.common.errors import ApiError, ErrorCode
from app.common.ids import ordered_pair_id, sha256_hex
from app.common.store.docstore import Query
from app.notifications.service import NotificationKind
from app.profiles.service import user_path
from app.usernames.rules import normalize

SEARCH_LIMIT = 20
MIN_PREFIX = 2
PREFIX_END = chr(0xF8FF)  # highest BMP private-use char: exclusive upper bound for prefix ranges


def request_path(sender: str, recipient: str) -> str:
    return f"friend_requests/{sha256_hex(f'{sender}>{recipient}')[:32]}"


def friendship_path(uid_a: str, uid_b: str) -> str:
    return f"friendships/{ordered_pair_id(uid_a, uid_b)}"


class FriendService:
    def __init__(self, container) -> None:
        self._c = container

    # ------------------------------------------------------------------------------------------ helpers
    async def _card(self, public_id: str) -> dict[str, Any] | None:
        profile = await self._c.store.get(f"public_profiles/{public_id}")
        if not profile:
            return None
        return {"public_id": public_id, "username": profile.get("username_display"),
                "avatar_id": profile.get("avatar_id"), "frame_id": profile.get("frame_id", "frame_none"),
                "league": profile.get("league"), "level": profile.get("level")}

    def _public_id(self, uid: str) -> str:
        if uid.startswith("bot:"):
            return self._c.bots.public_id(uid.removeprefix("bot:"))
        return self._c.profiles.public_id(uid)

    async def relationship(self, me: str, other: str) -> str:
        store = self._c.store
        friendship, outgoing, incoming = await store.get_many([friendship_path(me, other), request_path(me, other),
                                                               request_path(other, me)])
        if friendship:
            return "FRIEND"
        if outgoing and outgoing.get("state") in ("PENDING", "SUPPRESSED"):
            return "REQUEST_SENT"
        if incoming and incoming.get("state") == "PENDING":
            return "REQUEST_RECEIVED"
        return "NONE"

    async def are_friends(self, uid_a: str, uid_b: str) -> bool:
        if await self._c.safety.is_blocked_either_way(uid_a, uid_b):
            return False
        return bool(await self._c.store.get(friendship_path(uid_a, uid_b)))

    # ------------------------------------------------------------------------------------------ search
    async def search(self, uid: str, username: str) -> dict[str, Any]:
        prefix = normalize(username)
        if len(prefix) < MIN_PREFIX:
            raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "query_too_short"})
        blocked = await self._c.safety.block_set(uid)
        rows = await self._c.store.query(
            Query("username_registry").filter("state", "==", "ACTIVE").filter("name", ">=", prefix)
            .filter("name", "<", prefix + PREFIX_END).order("name").take(SEARCH_LIMIT + 1 + len(blocked)))
        items = []
        exact = None
        for row in rows:
            owner = row.data.get("uid")
            if not owner or owner == uid or owner in blocked:
                continue
            card = await self._card(self._public_id(owner))
            if not card:
                continue
            card["relationship"] = await self.relationship(uid, owner)
            if row.data.get("name") == prefix:
                exact = card
            else:
                items.append(card)
        ordered = ([exact] if exact else []) + items
        return {"schema_version": 1, "results": ordered[:SEARCH_LIMIT]}

    # ------------------------------------------------------------------------------------------ requests
    async def send_request(self, uid: str, target_public_id: str) -> dict[str, Any]:
        c = self._c
        target = await c.profiles.uid_for_public_id(target_public_id)
        if target == uid:
            raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "cannot_friend_self"})
        if await c.store.get(f"blocks/{uid}_{target}"):
            raise ApiError(ErrorCode.BLOCKED)
        blocked_by_target = bool(await c.store.get(f"blocks/{target}_{uid}"))
        now = c.clock.now_ms()

        def txn_fn(txn) -> str:
            friendship, outgoing, incoming = txn.get_many([friendship_path(uid, target), request_path(uid, target),
                                                           request_path(target, uid)])
            if friendship:
                return "FRIEND"
            if incoming and incoming.get("state") == "PENDING" and not blocked_by_target:
                # Mutual intent: accepting the reverse request creates the edge immediately.
                txn.update(request_path(target, uid), {"state": "ACCEPTED", "updated_at_ms": now})
                txn.set(friendship_path(uid, target), {"schema_version": 1, "member_uids": sorted([uid, target]),
                                                       "created_at_ms": now})
                return "FRIEND"
            if outgoing and outgoing.get("state") in ("PENDING", "SUPPRESSED"):
                return "REQUEST_SENT"
            # A request to someone who blocked the sender is stored but never delivered (no block reveal).
            txn.set(request_path(uid, target), {
                "schema_version": 1, "request_id": request_path(uid, target).split("/")[1], "sender_uid": uid,
                "recipient_uid": target, "state": "SUPPRESSED" if blocked_by_target else "PENDING",
                "created_at_ms": now, "updated_at_ms": now})
            return "REQUEST_SENT_NEW"

        state = await c.store.run_transaction(txn_fn)
        if state == "REQUEST_SENT_NEW" and not blocked_by_target:
            sender = await c.store.get(user_path(uid)) or {}
            await c.notifications.notify(target, NotificationKind.FRIEND_REQUEST, sender_uid=uid,
                                         data={"public_id": sender.get("public_id", "")},
                                         body_args=[sender.get("username_display") or ""])
        return {"schema_version": 1, "relationship": "REQUEST_SENT" if state.startswith("REQUEST") else state}

    async def respond(self, uid: str, request_id: str, accept: bool) -> dict[str, Any]:
        c = self._c
        now = c.clock.now_ms()
        doc = await c.store.get(f"friend_requests/{request_id}")
        if not doc or doc.get("recipient_uid") != uid:
            raise ApiError(ErrorCode.NOT_FOUND)
        sender = doc["sender_uid"]
        if accept and await c.safety.is_blocked_either_way(uid, sender):
            raise ApiError(ErrorCode.BLOCKED)

        def txn_fn(txn) -> str:
            request = txn.get(f"friend_requests/{request_id}")
            if not request or request.get("state") not in ("PENDING", "ACCEPTED", "DECLINED"):
                raise ApiError(ErrorCode.NOT_FOUND)
            if request["state"] != "PENDING":
                return request["state"]
            state = "ACCEPTED" if accept else "DECLINED"
            txn.update(f"friend_requests/{request_id}", {"state": state, "updated_at_ms": now})
            if accept:
                txn.set(friendship_path(uid, sender), {"schema_version": 1, "member_uids": sorted([uid, sender]),
                                                       "created_at_ms": now})
            return state

        return {"schema_version": 1, "state": await c.store.run_transaction(txn_fn)}

    async def remove(self, uid: str, target_public_id: str) -> dict[str, Any]:
        target = await self._c.profiles.uid_for_public_id(target_public_id)
        await self._c.store.delete(friendship_path(uid, target))
        for path in (request_path(uid, target), request_path(target, uid)):
            doc = await self._c.store.get(path)
            if doc and doc.get("state") in ("PENDING", "SUPPRESSED"):
                await self._c.store.update(path, {"state": "CANCELLED", "updated_at_ms": self._c.clock.now_ms()})
        return {"schema_version": 1, "relationship": "NONE"}

    # ------------------------------------------------------------------------------------------ listing
    async def overview(self, uid: str) -> dict[str, Any]:
        c = self._c
        blocked = await c.safety.block_set(uid)
        edges = await c.store.query(Query("friendships").filter("member_uids", "array_contains", uid))
        friends = []
        for edge in edges:
            other = next((m for m in edge.data["member_uids"] if m != uid), None)
            if not other or other in blocked:
                continue  # hidden and non-interactive while a block exists
            card = await self._card(self._public_id(other))
            if card:
                runtime = await c.store.get(f"user_runtime/{other}") or {}
                card["can_challenge"] = runtime.get("state", "IDLE") == "IDLE"
                card["since_ms"] = edge.data.get("created_at_ms")
                friends.append(card)
        incoming_rows = await c.store.query(Query("friend_requests").filter("recipient_uid", "==", uid)
                                            .filter("state", "==", "PENDING"))
        outgoing_rows = await c.store.query(Query("friend_requests").filter("sender_uid", "==", uid)
                                            .filter("state", "in", ["PENDING", "SUPPRESSED"]))
        incoming, outgoing = [], []
        for row, bucket, other_field in [(r, incoming, "sender_uid") for r in incoming_rows] + \
                                        [(r, outgoing, "recipient_uid") for r in outgoing_rows]:
            other = row.data[other_field]
            if other in blocked:
                continue
            card = await self._card(self._public_id(other))
            if card:
                bucket.append({"request_id": row.id, "created_at_ms": row.data.get("created_at_ms"), **card})
        friends.sort(key=lambda f: (f.get("username") or "").lower())
        return {"schema_version": 1, "friends": friends, "incoming_requests": incoming,
                "outgoing_requests": outgoing}

