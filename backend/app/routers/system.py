"""Health and latency probe endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.common import rate_limit
from app.common.api import Caller, authenticated, get_container
from app.container import Container

router = APIRouter()


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/v1/ping")
async def ping(caller: Caller = Depends(authenticated), c: Container = Depends(get_container)) -> dict:
    """Lightweight authenticated RTT probe (spec §21.2). Timing here is diagnostic only."""
    received = c.clock.now_ms()
    await c.rate_limiter.hit(rate_limit.PING, caller.uid)
    return {"schema_version": 1, "server_received_at_ms": received, "server_responded_at_ms": c.clock.now_ms()}
