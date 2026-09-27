"""Public catalog endpoints (spec §27.2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.common.api import Caller, authenticated
from app.questions.taxonomy import CATEGORIES

router = APIRouter(prefix="/v1")


@router.get("/categories")
async def categories(lang: str = Query("en", max_length=16), caller: Caller = Depends(authenticated)) -> dict:
    return {
        "schema_version": 1,
        "categories": [
            {
                "id": c.id,
                "name": c.names.get(lang, c.names["en"]),
                "icon": c.icon,
                "subcategories": [{"id": sid, "name": names.get(lang, names["en"])}
                                  for sid, names in c.subcategories.items()],
            }
            for c in CATEGORIES
        ],
    }
