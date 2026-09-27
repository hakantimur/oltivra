"""Push notifications via FCM (spec §34.2) behind a small port.

Respects per-user notification preferences, never notifies across a block, and throttles each kind per
recipient so reminders never feel spammy. Payloads carry only IDs/opaque tokens, never private data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

import anyio

from app.common.ids import sha256_hex
from app.common.store.docstore import DocStore, Query

log = logging.getLogger("oltivra.notifications")


class NotificationKind(StrEnum):
    FRIEND_REQUEST = "FRIEND_REQUEST"
    FRIEND_CHALLENGE = "FRIEND_CHALLENGE"
    CHALLENGE_ACCEPTED = "CHALLENGE_ACCEPTED"
    LEADERBOARD_ENDING = "LEADERBOARD_ENDING"
    MISSION_REMINDER = "MISSION_REMINDER"
    LEAGUE_RESULT = "LEAGUE_RESULT"


PREFERENCE = {
    NotificationKind.FRIEND_REQUEST: "friend_requests",
    NotificationKind.FRIEND_CHALLENGE: "challenges",
    NotificationKind.CHALLENGE_ACCEPTED: "challenges",
    NotificationKind.LEADERBOARD_ENDING: "leaderboard",
    NotificationKind.MISSION_REMINDER: "missions",
    NotificationKind.LEAGUE_RESULT: "league",
}
# Minimum spacing per recipient and kind (ms). Social events are near-real-time; reminders are rare.
THROTTLE_MS = {
    NotificationKind.FRIEND_REQUEST: 60_000,
    NotificationKind.FRIEND_CHALLENGE: 0,
    NotificationKind.CHALLENGE_ACCEPTED: 0,
    NotificationKind.LEADERBOARD_ENDING: 6 * 86_400_000,
    NotificationKind.MISSION_REMINDER: 20 * 3_600_000,
    NotificationKind.LEAGUE_RESULT: 3_600_000,
}


@dataclass
class Push:
    token: str
    kind: str
    data: dict[str, str]
    title_key: str
    body_key: str
    body_args: list[str] = field(default_factory=list)


class PushSender(Protocol):
    async def send(self, push: Push) -> bool: ...


class RecordingPushSender:
    def __init__(self) -> None:
        self.sent: list[Push] = []

    async def send(self, push: Push) -> bool:
        self.sent.append(push)
        return True


class FcmPushSender:
    def __init__(self, app, limiter: anyio.CapacityLimiter) -> None:
        self._app = app
        self._limiter = limiter

    async def send(self, push: Push) -> bool:
        from firebase_admin import exceptions, messaging

        message = messaging.Message(
            token=push.token,
            data={"kind": push.kind, **push.data},
            notification=None,
            android=messaging.AndroidConfig(notification=messaging.AndroidNotification(
                title_loc_key=push.title_key, body_loc_key=push.body_key, body_loc_args=push.body_args)),
            apns=messaging.APNSConfig(payload=messaging.APNSPayload(aps=messaging.Aps(alert=messaging.ApsAlert(
                title_loc_key=push.title_key, loc_key=push.body_key, loc_args=push.body_args)))),
        )
        try:
            await anyio.to_thread.run_sync(lambda: messaging.send(message, app=self._app), limiter=self._limiter)
            return True
        except (exceptions.FirebaseError, ValueError) as exc:
            log.info("push_failed", extra={"kind": push.kind, "error": type(exc).__name__})
            return False


def device_path(token: str) -> str:
    return f"device_tokens/{sha256_hex(token)[:40]}"


class NotificationService:
    def __init__(self, store: DocStore, clock, sender: PushSender) -> None:
        self._store = store
        self._clock = clock
        self.sender = sender

    async def register_device(self, uid: str, token: str, platform: str) -> None:
        await self._store.set(device_path(token), {"schema_version": 1, "uid": uid, "token": token,
                                                   "platform": platform, "updated_at_ms": self._clock.now_ms()})

    async def unregister_device(self, uid: str, token: str) -> None:
        doc = await self._store.get(device_path(token))
        if doc and doc.get("uid") == uid:
            await self._store.delete(device_path(token))

    async def notify(self, recipient_uid: str, kind: NotificationKind, *, data: dict[str, str] | None = None,
                     body_args: list[str] | None = None, sender_uid: str | None = None) -> int:
        """Best-effort delivery; never raises into the business flow. Returns pushes sent."""
        try:
            return await self._notify(recipient_uid, kind, data or {}, body_args or [], sender_uid)
        except Exception:  # noqa: BLE001
            log.exception("notify_failed", extra={"kind": kind.value})
            return 0

    async def _notify(self, recipient_uid: str, kind: NotificationKind, data: dict[str, str], body_args: list[str],
                      sender_uid: str | None) -> int:
        if recipient_uid.startswith("bot:"):
            return 0
        user = await self._store.get(f"users/{recipient_uid}")
        if not user or user.get("status", "ACTIVE") != "ACTIVE":
            return 0
        if not (user.get("notifications") or {}).get(PREFERENCE[kind], True):
            return 0
        if sender_uid:
            blocks = await self._store.get_many([f"blocks/{recipient_uid}_{sender_uid}",
                                                 f"blocks/{sender_uid}_{recipient_uid}"])
            if any(blocks):
                return 0
        now = self._clock.now_ms()
        throttle = THROTTLE_MS[kind]
        if throttle:
            path = f"notification_throttle/{recipient_uid}_{kind.value}"
            last = await self._store.get(path)
            if last and now - int(last.get("sent_at_ms", 0)) < throttle:
                return 0
            await self._store.set(path, {"uid": recipient_uid, "sent_at_ms": now})
        rows = await self._store.query(Query("device_tokens").filter("uid", "==", recipient_uid))
        sent = 0
        for row in rows:
            push = Push(token=row.data["token"], kind=kind.value, data={k: str(v) for k, v in data.items()},
                        title_key=f"push_{kind.value.lower()}_title", body_key=f"push_{kind.value.lower()}_body",
                        body_args=body_args)
            if await self.sender.send(push):
                sent += 1
        return sent
