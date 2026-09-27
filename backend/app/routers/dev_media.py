"""Question media for the in-memory dev server (pairs with ``DevMediaSigner``).

Only answers when the API runs with ``env=dev`` and the in-memory store, where uploads live in process memory
and no storage emulator exists. Everywhere else this route is a 404 and media comes from Cloud Storage.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.common.api import get_container
from app.common.errors import ApiError, ErrorCode
from app.common.media import MemoryMediaUploader
from app.container import Container

router = APIRouter()


@router.get("/dev/media/{storage_path:path}", include_in_schema=False)
async def dev_media(storage_path: str, exp: int = Query(...), c: Container = Depends(get_container)) -> Response:
    uploader = c.media_uploader
    if c.settings.env != "dev" or not isinstance(uploader, MemoryMediaUploader):
        raise ApiError(ErrorCode.NOT_FOUND)
    if exp < c.clock.now_ms():  # same contract as a signed URL: expired links stop working
        raise ApiError(ErrorCode.FORBIDDEN, detail={"reason": "expired"})
    stored = uploader.objects.get(storage_path)
    if stored is None:
        raise ApiError(ErrorCode.NOT_FOUND)
    data, content_type = stored
    return Response(data, media_type=content_type, headers={"cache-control": "private, max-age=60"})
