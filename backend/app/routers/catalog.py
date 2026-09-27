"""Public catalog endpoints (spec §27.2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.common.api import Caller, authenticated, get_container
from app.container import Container

router = APIRouter(prefix="/v1")


@router.get("/categories")
async def categories(lang: str = Query("en", max_length=16), caller: Caller = Depends(authenticated),
                     c: Container = Depends(get_container)) -> dict:
    return {
        "schema_version": 1,
        "categories": [
            {
                "id": cat["id"],
                "name": cat["names"].get(lang, cat["names"]["en"]),
                "icon": cat["icon"],
                "subcategories": [{"id": sid, "name": names.get(lang, names["en"])}
                                  for sid, names in cat["subcategories"].items()],
            }
            for cat in await c.categories.all()
        ],
    }
