"""Firebase ID token and App Check verification ports (spec §15.2)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import anyio

from app.common.errors import ApiError, ErrorCode

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class VerifiedToken:
    uid: str
    claims: dict[str, Any] = field(default_factory=dict)

    @property
    def is_admin(self) -> bool:
        return bool(self.claims.get("admin"))

    @property
    def used_mfa(self) -> bool:
        firebase = self.claims.get("firebase") or {}
        return bool(firebase.get("sign_in_second_factor"))

    @property
    def auth_time_s(self) -> int:
        return int(self.claims.get("auth_time", 0))


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> VerifiedToken: ...


class AppCheckVerifier(Protocol):
    async def verify(self, token: str | None) -> None: ...


class FakeTokenVerifier:
    """Dev/test only: ``test:<uid>`` or ``test:<uid>:admin`` or ``test:<uid>:admin:mfa``."""

    async def verify(self, token: str) -> VerifiedToken:
        parts = token.split(":")
        if len(parts) < 2 or parts[0] != "test" or not parts[1]:
            raise ApiError(ErrorCode.UNAUTHENTICATED)
        flags = set(parts[2:])
        claims: dict[str, Any] = {"auth_time": 0}
        if "admin" in flags:
            claims["admin"] = True
        if "mfa" in flags:
            claims["firebase"] = {"sign_in_second_factor": "totp"}
        if "fresh" in flags:
            claims["auth_time"] = 10**12
        return VerifiedToken(parts[1], claims)


class FirebaseTokenVerifier:
    def __init__(self, app, limiter: anyio.CapacityLimiter) -> None:
        self._app = app
        self._limiter = limiter

    async def verify(self, token: str) -> VerifiedToken:
        from firebase_admin import auth

        def _verify() -> dict[str, Any]:
            return auth.verify_id_token(token, app=self._app, check_revoked=False)

        try:
            claims = await anyio.to_thread.run_sync(_verify, limiter=self._limiter)
        except Exception as exc:  # any verification failure is an auth failure
            raise ApiError(ErrorCode.UNAUTHENTICATED) from exc
        return VerifiedToken(claims["uid"], claims)


class NoAppCheck:
    """``off`` mode (local dev): accepts any request."""

    async def verify(self, token: str | None) -> None:
        return None


class DebugAppCheck:
    """``debug`` mode (dev/stage only): real verification, but debug tokens are accepted by Firebase."""

    def __init__(self, inner: AppCheckVerifier) -> None:
        self._inner = inner

    async def verify(self, token: str | None) -> None:
        await self._inner.verify(token)


class MonitorAppCheck:
    """``monitor`` mode (stage rollout): verifies tokens and logs failures, but never rejects the request."""

    def __init__(self, inner: AppCheckVerifier) -> None:
        self._inner = inner

    async def verify(self, token: str | None) -> None:
        try:
            await self._inner.verify(token)
        except ApiError as err:
            _log.warning("app_check_monitor_failure", extra={
                "has_token": bool(token), "reason": _failure_reason(err), "token_app": _token_app(token)})


def _failure_reason(err: ApiError) -> str:
    """Why verification failed, without the token itself (the cause is the Firebase Admin error, if any)."""
    cause = err.__cause__
    if cause is None:
        return "missing_token"
    return f"{type(cause).__name__}: {str(cause)[:160]}"


def _token_app(token: str | None) -> str:
    """The Firebase app id (``sub``) claimed by an unverified token — tells Android, iOS and debug clients apart."""
    if not token:
        return "-"
    try:
        import jwt

        return str(jwt.decode(token, options={"verify_signature": False}).get("sub", "?"))[:80]
    except Exception:  # noqa: BLE001 - a malformed token is itself the answer
        return "malformed"


class FirebaseAppCheck:
    def __init__(self, app, limiter: anyio.CapacityLimiter) -> None:
        self._app = app
        self._limiter = limiter

    async def verify(self, token: str | None) -> None:
        if not token:
            raise ApiError(ErrorCode.APP_CHECK_FAILED)
        from firebase_admin import app_check

        try:
            await anyio.to_thread.run_sync(lambda: app_check.verify_token(token, app=self._app),
                                           limiter=self._limiter)
        except Exception as exc:
            raise ApiError(ErrorCode.APP_CHECK_FAILED) from exc


class StaticAppCheck:
    """Test helper: accepts only the configured token."""

    def __init__(self, valid_token: str = "valid-app-check") -> None:
        self.valid_token = valid_token

    async def verify(self, token: str | None) -> None:
        if token != self.valid_token:
            raise ApiError(ErrorCode.APP_CHECK_FAILED)
