"""Health and latency probe endpoints."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.common import rate_limit
from app.common.api import Caller, authenticated, get_container
from app.container import Container

router = APIRouter()
_log = logging.getLogger("oltivra.ads")


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/v1/ping")
async def ping(caller: Caller = Depends(authenticated), c: Container = Depends(get_container)) -> dict:
    """Lightweight authenticated RTT probe (spec §21.2). Timing here is diagnostic only."""
    received = c.clock.now_ms()
    await c.rate_limiter.hit(rate_limit.PING, caller.uid)
    return {"schema_version": 1, "server_received_at_ms": received, "server_responded_at_ms": c.clock.now_ms()}


class AdDiagnostic(BaseModel):
    """One step of the client's ad pipeline: UMP consent, an ad load or an ad show (diagnostics only)."""

    stage: Literal["consent", "load_interstitial", "load_rewarded", "show"]
    ok: bool
    code: str = Field(default="", max_length=32)
    detail: str = Field(default="", max_length=200)


@router.post("/v1/diagnostics/ads", status_code=204)
async def ad_diagnostic(body: AdDiagnostic, caller: Caller = Depends(authenticated),
                        c: Container = Depends(get_container)) -> None:
    """Logs why a client could not request or show ads; nothing is stored. No uid in the line, just the client."""
    await c.rate_limiter.hit(rate_limit.AD_DIAGNOSTIC, caller.uid)
    _log.info("ad_diagnostic", extra={"stage": body.stage, "ok": body.ok, "code": body.code, "detail": body.detail})
