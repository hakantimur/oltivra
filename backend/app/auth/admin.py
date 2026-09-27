"""Firebase Auth administration port (user deletion, custom claims)."""

from __future__ import annotations

from typing import Any, Protocol

import anyio


class AuthAdmin(Protocol):
    async def delete_user(self, uid: str) -> None: ...

    async def set_custom_claims(self, uid: str, claims: dict[str, Any]) -> None: ...


class FakeAuthAdmin:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.claims: dict[str, dict[str, Any]] = {}

    async def delete_user(self, uid: str) -> None:
        if uid not in self.deleted:
            self.deleted.append(uid)

    async def set_custom_claims(self, uid: str, claims: dict[str, Any]) -> None:
        self.claims[uid] = dict(claims)


class FirebaseAuthAdmin:
    def __init__(self, app, limiter: anyio.CapacityLimiter) -> None:
        self._app = app
        self._limiter = limiter

    async def delete_user(self, uid: str) -> None:
        from firebase_admin import auth

        def _delete() -> None:
            try:
                auth.delete_user(uid, app=self._app)
            except auth.UserNotFoundError:
                pass  # idempotent retry

        await anyio.to_thread.run_sync(_delete, limiter=self._limiter)

    async def set_custom_claims(self, uid: str, claims: dict[str, Any]) -> None:
        from firebase_admin import auth

        await anyio.to_thread.run_sync(lambda: auth.set_custom_user_claims(uid, claims, app=self._app),
                                       limiter=self._limiter)
