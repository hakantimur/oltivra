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
    from app.common.errors import ApiError, ErrorCode
    from app.common.tasks import QUEUE_FAMILY, TaskKind

    body = await request.json()
    # Each queue may only run its own task kinds (a task cannot be replayed through another family's route).
    try:
        kind = TaskKind(body.get("task_kind"))
    except ValueError as exc:
        raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "unknown_task_kind"}) from exc
    if QUEUE_FAMILY[kind] != family:
        raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "task_family_mismatch"})
    result = await dispatch_task(c, body)
    return {"ok": True, "result": result}


# Provider callbacks authenticate by signature, not by our service identity.
provider_router = APIRouter(prefix="/internal", include_in_schema=False)


@provider_router.get("/ads/admob-ssv")
async def admob_ssv(request: Request, c: Container = Depends(get_container)) -> dict:
    """AdMob rewarded SSV callback: ECDSA-signed query string (spec §31.2)."""
    return await c.rewards.handle_ssv(request.url.query)


@provider_router.post("/purchases/google-rtdn", dependencies=[Depends(_service_auth)])
async def google_rtdn(request: Request, c: Container = Depends(get_container)) -> dict:
    """Pub/Sub push (OIDC-authenticated) carrying Google Play RTDN (spec §31.4)."""
    return {"ok": True, "result": await c.purchases.handle_google_rtdn(await request.json())}


@provider_router.post("/purchases/apple-notifications")
async def apple_notifications(request: Request, c: Container = Depends(get_container)) -> dict:
    """App Store Server Notifications V2: JWS verified against the pinned Apple root (spec §31.5)."""
    return {"ok": True, "result": await c.purchases.handle_apple_notification(await request.json())}


# Cloud Scheduler targets (OIDC-authenticated in prod, spec §20.6).
maintenance_router = APIRouter(prefix="/internal/maintenance", include_in_schema=False)


@maintenance_router.post("/{job}", dependencies=[Depends(_service_auth)])
async def run_maintenance(job: str, c: Container = Depends(get_container)) -> dict:
    from app.common.errors import ApiError, ErrorCode
    from app.maintenance.service import JOBS

    fn = JOBS.get(job)
    if fn is None:
        raise ApiError(ErrorCode.NOT_FOUND, detail={"reason": "unknown_job"})
    return {"ok": True, "job": job, "result": await fn(c.maintenance)}
