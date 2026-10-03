"""FastAPI application factory."""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.common.errors import ApiError, ErrorCode
from app.common.logging import client_var, configure_logging, request_id_var
from app.common.settings import Settings
from app.container import Container
from app.routers import register_routers

log = logging.getLogger("oltivra.http")


def _client(request: Request) -> str:
    """``<platform>/<build>`` sent by the app; clamped so a hostile header cannot bloat log lines."""
    platform = request.headers.get("x-client-platform", "")[:16]
    build = request.headers.get("x-client-build", "")[:16]
    return f"{platform or '?'}/{build or '?'}" if platform or build else "-"


def create_app(container: Container | None = None) -> FastAPI:
    container = container or Container(Settings())

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if container.settings.env in ("stage", "prod"):
            configure_logging()
        await container.startup()
        try:
            yield
        finally:
            await container.shutdown()

    public_docs = container.settings.env != "prod"
    app = FastAPI(
        lifespan=lifespan,
        title="Oltivra API",
        version="1.0.0",
        docs_url="/docs" if public_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if public_docs else None,
    )
    app.state.container = container

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if 8 <= len(incoming) <= 64 else str(uuid.uuid4())
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        client_token = client_var.set(_client(request))
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
            client_var.reset(client_token)
        response.headers["x-request-id"] = request_id
        log.info("request", extra={"path": request.url.path, "method": request.method,
                                   "status": response.status_code,
                                   "latency_ms": round((time.perf_counter() - started) * 1000, 1)})
        return response

    def _rid(request: Request) -> str:
        return getattr(request.state, "request_id", "-")

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        headers = {"retry-after": str(exc.retry_after_s)} if exc.retry_after_s else None
        return JSONResponse(exc.envelope(_rid(request)), status_code=exc.status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        fields = [".".join(str(p) for p in err.get("loc", ())) for err in exc.errors()]
        err = ApiError(ErrorCode.INVALID_REQUEST, detail={"fields": fields})
        return JSONResponse(err.envelope(_rid(request)), status_code=err.status)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        code = {404: ErrorCode.NOT_FOUND, 405: ErrorCode.INVALID_REQUEST, 401: ErrorCode.UNAUTHENTICATED,
                403: ErrorCode.FORBIDDEN}.get(exc.status_code, ErrorCode.INVALID_REQUEST)
        err = ApiError(code, status=exc.status_code)
        return JSONResponse(err.envelope(_rid(request)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error", extra={"path": request.url.path})
        err = ApiError(ErrorCode.INTERNAL)
        return JSONResponse(err.envelope(_rid(request)), status_code=500)

    register_routers(app)
    return app


def app_from_env() -> FastAPI:
    return create_app()
