"""Mutation idempotency (spec §19.1).

Same UID + endpoint + key + semantic payload -> original response.
Same key with a different payload -> 409 IDEMPOTENCY_KEY_REUSED.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from app.common.clock import Clock, ms_to_datetime
from app.common.errors import ApiError, ErrorCode
from app.common.ids import is_uuid4, sha256_hex
from app.common.store.docstore import DocStore

RETENTION_MS = 48 * 3_600_000
IN_PROGRESS_STALE_MS = 30_000
_NON_SEMANTIC = {"request_id", "client_diagnostics"}


def semantic_hash(payload: dict[str, Any]) -> str:
    cleaned = {k: v for k, v in payload.items() if k not in _NON_SEMANTIC}
    return sha256_hex(json.dumps(cleaned, sort_keys=True, separators=(",", ":"), default=str))


def resolve_key(header_key: str | None, body_request_id: str | None) -> str:
    """Header and body must agree when both are present; at least one is required (UUIDv4)."""
    if header_key and body_request_id and header_key != body_request_id:
        raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "idempotency_key_mismatch"})
    key = header_key or body_request_id
    if not key or not is_uuid4(key):
        raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "request_id_required"})
    return key


class IdempotencyService:
    def __init__(self, store: DocStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    @staticmethod
    def record_path(uid: str, endpoint: str, key: str) -> str:
        return f"idempotency_records/{sha256_hex(f'{uid}|{endpoint}|{key}')}"

    async def execute(
        self,
        uid: str,
        endpoint: str,
        key: str,
        payload: dict[str, Any],
        handler: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        path = self.record_path(uid, endpoint, key)
        payload_hash = semantic_hash(payload)
        now = self._clock.now_ms()

        def reserve(txn) -> dict[str, Any] | None:
            record = txn.get(path)
            if record and record["expires_at_ms"] > now:
                if record["payload_hash"] != payload_hash:
                    raise ApiError(ErrorCode.IDEMPOTENCY_KEY_REUSED)
                if record["state"] == "DONE":
                    return record
                if now - record["created_at_ms"] < IN_PROGRESS_STALE_MS:
                    raise ApiError(ErrorCode.CONFLICT, retryable=True, retry_after_s=1)
            txn.set(path, {
                "schema_version": 1,
                "uid": uid,
                "endpoint": endpoint,
                "payload_hash": payload_hash,
                "state": "IN_PROGRESS",
                "created_at_ms": now,
                "expires_at_ms": now + RETENTION_MS,
                "expires_at": ms_to_datetime(now + RETENTION_MS),
            })
            return None

        existing = await self._store.run_transaction(reserve)
        if existing is not None:
            return self._replay(existing)

        try:
            response = await handler()
        except ApiError as err:
            if err.retryable:
                await self._store.delete(path)
            else:
                await self._store.update(path, {
                    "state": "DONE",
                    "outcome": {"kind": "error", "code": err.code.value, "status": err.status,
                                "detail": err.detail},
                })
            raise
        except BaseException:
            await self._store.delete(path)
            raise
        await self._store.update(path, {"state": "DONE", "outcome": {"kind": "ok", "body": response}})
        return response

    @staticmethod
    def _replay(record: dict[str, Any]) -> dict[str, Any]:
        outcome = record["outcome"]
        if outcome["kind"] == "ok":
            return outcome["body"]
        raise ApiError(ErrorCode(outcome["code"]), status=outcome["status"], detail=outcome.get("detail"))
