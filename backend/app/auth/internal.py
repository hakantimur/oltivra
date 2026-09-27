"""Service authentication for /internal routes (Cloud Tasks / Scheduler / Pub/Sub OIDC)."""

from __future__ import annotations

import hmac
from typing import Protocol

import anyio

from app.common.errors import ApiError, ErrorCode


class InternalAuth(Protocol):
    async def verify(self, authorization: str | None, shared_secret: str | None) -> None: ...


class SharedSecretInternalAuth:
    """Local/dev only; production requires OIDC (enforced by Settings)."""

    def __init__(self, secret: str) -> None:
        self._secret = secret

    async def verify(self, authorization: str | None, shared_secret: str | None) -> None:
        if not shared_secret or not hmac.compare_digest(shared_secret, self._secret):
            raise ApiError(ErrorCode.FORBIDDEN)


class OidcInternalAuth:
    def __init__(self, audience: str, allowed_emails: set[str]) -> None:
        self._audience = audience
        self._allowed = allowed_emails

    async def verify(self, authorization: str | None, shared_secret: str | None) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise ApiError(ErrorCode.FORBIDDEN)
        token = authorization.removeprefix("Bearer ")
        from google.auth.transport import requests as grequests
        from google.oauth2 import id_token

        def _verify() -> dict:
            return id_token.verify_oauth2_token(token, grequests.Request(), audience=self._audience)

        try:
            claims = await anyio.to_thread.run_sync(_verify)
        except Exception as exc:
            raise ApiError(ErrorCode.FORBIDDEN) from exc
        if not claims.get("email_verified") or claims.get("email") not in self._allowed:
            raise ApiError(ErrorCode.FORBIDDEN)
