"""Router registration. Each feature module exposes ``router``."""

from __future__ import annotations

from fastapi import FastAPI


def register_routers(app: FastAPI) -> None:
    from app.routers import internal, system

    app.include_router(system.router)
    app.include_router(internal.router)
