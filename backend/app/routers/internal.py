"""Internal task endpoints (spec §27.7). Reject user tokens; require service authentication."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.common.api import get_container
from app.container import Container
from app.tasks.dispatch import dispatch_task

router = APIRouter(prefix="/internal/tasks", include_in_schema=False)


async def _service_auth(request: Request, c: Container = Depends(get_container)) -> None:
    await c.internal_auth.verify(request.headers.get("authorization"), request.headers.get("x-internal-auth"))


@router.post("/{family}", dependencies=[Depends(_service_auth)])
async def run_task(family: str, request: Request, c: Container = Depends(get_container)) -> dict:
    body = await request.json()
    result = await dispatch_task(c, body)
    return {"ok": True, "result": result}
