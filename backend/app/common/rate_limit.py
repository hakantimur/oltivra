"""Distributed fixed-window logical rate limits (spec §28.3). State is server-owned in the DocStore."""

from __future__ import annotations

from dataclasses import dataclass

from app.common.clock import Clock, ms_to_datetime
from app.common.errors import ApiError, ErrorCode
from app.common.ids import sha256_hex
from app.common.store.docstore import DocStore


@dataclass(frozen=True)
class Limit:
    name: str
    limit: int
    window_s: int


# Defaults from spec §28.3.
ANSWER = Limit("answer", 5, 15)
QUEUE_JOIN = Limit("queue_join", 4, 60)
QUEUE_LEAVE = Limit("queue_leave", 6, 60)
USERNAME_SEARCH = Limit("username_search", 20, 60)
FRIEND_REQUEST = Limit("friend_request", 20, 86_400)
PLAYER_REPORT = Limit("player_report", 10, 86_400)
QUESTION_REPORT = Limit("question_report", 30, 86_400)
REACTION = Limit("reaction", 6, 15)
SYNC = Limit("sync", 20, 15)
SYNC_EVENT = Limit("sync_event", 1, 60)
REWARD_OFFER = Limit("reward_offer", 10, 3_600)
PING = Limit("ping", 30, 60)
GENERIC_WRITE = Limit("generic_write", 60, 60)
WEB_DELETE = Limit("web_delete", 5, 3_600)


class RateLimiter:
    def __init__(self, store: DocStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    async def hit(self, limit: Limit, subject: str) -> None:
        now = self._clock.now_ms()
        window_ms = limit.window_s * 1000
        window = now // window_ms
        path = f"rate_limits/{sha256_hex(f'{limit.name}|{subject}')}_{window}"
        expires = (window + 1) * window_ms

        def bump(txn) -> None:
            doc = txn.get(path)
            count = doc["count"] if doc else 0
            if count >= limit.limit:
                raise ApiError(ErrorCode.RATE_LIMITED, retry_after_s=max(1, (expires - now + 999) // 1000))
            txn.set(path, {"count": count + 1, "limit": limit.name, "expires_at": ms_to_datetime(expires)})

        await self._store.run_transaction(bump)
