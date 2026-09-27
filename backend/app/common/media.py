"""Short-lived signed delivery URLs for current-round question media (spec §22.2, §34.1)."""

from __future__ import annotations

import datetime
from typing import Protocol
from urllib.parse import quote

import anyio


class MediaSigner(Protocol):
    async def sign(self, storage_path: str, expires_at_ms: int) -> str: ...


class EmulatorMediaSigner:
    """Local development: the storage emulator serves objects directly (no real signature)."""

    def __init__(self, host: str, bucket: str) -> None:
        self._host = host
        self._bucket = bucket

    async def sign(self, storage_path: str, expires_at_ms: int) -> str:
        return (f"http://{self._host}/v0/b/{self._bucket}/o/{quote(storage_path, safe='')}"
                f"?alt=media&exp={expires_at_ms}")


class GcsMediaSigner:
    """V4 signed URL; uses IAM signBlob on Cloud Run, so it is always called outside RTDB transactions."""

    def __init__(self, bucket: str, service_account_email: str, limiter: anyio.CapacityLimiter) -> None:
        from google.cloud import storage

        self._bucket = storage.Client().bucket(bucket)
        self._sa = service_account_email
        self._limiter = limiter

    async def sign(self, storage_path: str, expires_at_ms: int) -> str:
        import google.auth
        from google.auth.transport import requests as grequests

        def _sign() -> str:
            credentials, _ = google.auth.default()
            credentials.refresh(grequests.Request())
            blob = self._bucket.blob(storage_path)
            return blob.generate_signed_url(
                version="v4",
                expiration=datetime.datetime.fromtimestamp(expires_at_ms / 1000, tz=datetime.UTC),
                method="GET",
                service_account_email=self._sa,
                access_token=credentials.token,
            )

        return await anyio.to_thread.run_sync(_sign, limiter=self._limiter)
