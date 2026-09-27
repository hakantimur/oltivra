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


class DevMediaSigner:
    """In-memory dev server: the API itself serves uploaded media at ``/dev/media`` (see routers/dev_media.py).

    ``base_url`` is the address the device uses for the API (the Android emulator reaches the host at 10.0.2.2).
    """

    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")

    async def sign(self, storage_path: str, expires_at_ms: int) -> str:
        return f"{self._base}/dev/media/{quote(storage_path, safe='')}?exp={expires_at_ms}"


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


class MediaObjectExists(Exception):
    """The versioned object already exists; question media is never overwritten in place (spec §34.1)."""


class MediaUploader(Protocol):
    async def put(self, storage_path: str, data: bytes, content_type: str, cache_control: str | None = None
                  ) -> None:
        """Create-only upload: raises MediaObjectExists instead of replacing an existing object."""
        ...


class MemoryMediaUploader:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.cache_control: dict[str, str | None] = {}

    async def put(self, storage_path: str, data: bytes, content_type: str, cache_control: str | None = None
                  ) -> None:
        if storage_path in self.objects:
            raise MediaObjectExists(storage_path)
        self.objects[storage_path] = (data, content_type)
        self.cache_control[storage_path] = cache_control


class EmulatorMediaUploader:
    """Uploads through the Storage emulator's GCS JSON API."""

    def __init__(self, host: str, bucket: str) -> None:
        self._host = host
        self._bucket = bucket

    async def put(self, storage_path: str, data: bytes, content_type: str, cache_control: str | None = None
                  ) -> None:
        import httpx

        url = f"http://{self._host}/upload/storage/v1/b/{self._bucket}/o"
        headers = {"content-type": content_type}
        if cache_control:
            headers["cache-control"] = cache_control
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(url, params={"uploadType": "media", "name": storage_path, "ifGenerationMatch": "0"},
                                    content=data, headers=headers)
            if res.status_code == 412:
                raise MediaObjectExists(storage_path)
            res.raise_for_status()


class GcsMediaUploader:
    def __init__(self, bucket: str, limiter: anyio.CapacityLimiter) -> None:
        from google.cloud import storage

        self._bucket = storage.Client().bucket(bucket)
        self._limiter = limiter

    async def put(self, storage_path: str, data: bytes, content_type: str, cache_control: str | None = None
                  ) -> None:
        from google.api_core.exceptions import PreconditionFailed

        blob = self._bucket.blob(storage_path)
        blob.cache_control = cache_control

        def _upload() -> None:
            # if_generation_match=0: the write succeeds only when no live object exists at this path.
            blob.upload_from_string(data, content_type=content_type, if_generation_match=0)

        try:
            await anyio.to_thread.run_sync(_upload, limiter=self._limiter)
        except PreconditionFailed as exc:
            raise MediaObjectExists(storage_path) from exc
