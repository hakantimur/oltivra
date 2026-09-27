"""FastAPI dependencies shared by every router: container, caller identity, idempotent mutations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Request

from app.auth.verifiers import VerifiedToken
from app.common.errors import ApiError, ErrorCode
from app.common.idempotency import resolve_key
from app.container import Container

ACCOUNT_BLOCKING_STATUSES = {
    "SUSPENDED": ErrorCode.ACCOUNT_SUSPENDED,
    "BANNED": ErrorCode.ACCOUNT_SUSPENDED,
    "DELETION_PENDING": ErrorCode.ACCOUNT_DELETION_PENDING,
    "DELETED": ErrorCode.ACCOUNT_DELETION_PENDING,
}


def get_container(request: Request) -> Container:
    return request.app.state.container


@dataclass(frozen=True)
class Caller:
    uid: str
    token: VerifiedToken
    user: dict[str, Any] | None = None

    @property
    def has_profile(self) -> bool:
        return bool(self.user and self.user.get("username_normalized") and self.user.get("avatar_id"))


async def authenticated(request: Request, c: Container = Depends(get_container)) -> Caller:
    """Firebase ID token + App Check (spec §15.2 steps 1–2)."""
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise ApiError(ErrorCode.UNAUTHENTICATED)
    token = await c.token_verifier.verify(header.removeprefix("Bearer ").strip())
    await c.app_check.verify(request.headers.get("x-firebase-appcheck"))
    return Caller(token.uid, token)


async def account_caller(caller: Caller = Depends(authenticated), c: Container = Depends(get_container)) -> Caller:
    """Adds account-state enforcement (step 3). Missing profile is allowed (onboarding)."""
    user = await c.store.get(f"users/{caller.uid}")
    if user:
        status = user.get("status", "ACTIVE")
        if status in ACCOUNT_BLOCKING_STATUSES:
            suspended_until = user.get("suspended_until_ms")
            if not (status == "SUSPENDED" and suspended_until and suspended_until <= c.clock.now_ms()):
                raise ApiError(ACCOUNT_BLOCKING_STATUSES[status])
    return Caller(caller.uid, caller.token, user)


async def player(caller: Caller = Depends(account_caller)) -> Caller:
    """A fully onboarded player (username + avatar + consent)."""
    if not caller.has_profile:
        raise ApiError(ErrorCode.PROFILE_INCOMPLETE)
    return caller


async def run_mutation(
    c: Container,
    request: Request,
    caller: Caller,
    endpoint: str,
    payload: dict[str, Any],
    handler: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    key = resolve_key(request.headers.get("x-idempotency-key"), payload.get("request_id"))
    return await c.idempotency.execute(caller.uid, endpoint, key, payload, handler)
