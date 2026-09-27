"""Router registration. Each feature module exposes ``router``."""

from __future__ import annotations

from fastapi import FastAPI


def register_routers(app: FastAPI) -> None:
    from app.routers import (
        admin,
        admin_moderation,
        catalog,
        internal,
        legal,
        matches,
        monetization,
        profile,
        progression,
        safety,
        session,
        social,
        synova,
        system,
        web,
    )

    app.include_router(system.router)
    app.include_router(session.router)
    app.include_router(profile.router)
    app.include_router(safety.router)
    app.include_router(catalog.router)
    app.include_router(synova.router)
    app.include_router(matches.router)
    app.include_router(progression.router)
    app.include_router(social.router)
    app.include_router(monetization.router)
    app.include_router(admin.router)
    app.include_router(admin_moderation.router)
    app.include_router(internal.router)
    app.include_router(internal.provider_router)
    app.include_router(internal.maintenance_router)
    app.include_router(web.router)
    app.include_router(legal.router)
