"""Public Terms of Service and Privacy Policy (store readiness; linked from onboarding, Settings and stores).

``GET /legal/{terms|privacy}`` serves a standalone HTML page; ``GET /v1/legal/{terms|privacy}`` returns the same
content as JSON for in-app rendering. Both are public (no sign-in) and carry the version players accept.
"""

from __future__ import annotations

import html

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from app.common.api import get_container
from app.common.errors import ApiError, ErrorCode
from app.container import Container
from app.legal.documents import DOCUMENTS, LegalIdentity, render
from app.profiles.service import PRIVACY_VERSION, TERMS_VERSION

router = APIRouter()

VERSIONS = {"terms": TERMS_VERSION, "privacy": PRIVACY_VERSION}
UNSET = "[not configured]"


def identity(c: Container) -> LegalIdentity:
    s = c.settings
    return LegalIdentity(operator=s.legal_operator_name or UNSET, contact=s.legal_contact_email or UNSET,
                         address=s.legal_address, law=s.legal_governing_law or UNSET,
                         effective=s.legal_effective_date)


def _language(request: Request, lang: str | None) -> str:
    if lang:
        return lang.lower()[:2]
    accept = request.headers.get("accept-language", "")
    return accept.split(",")[0].strip().lower()[:2] or "en"


def _document(doc: str) -> str:
    if doc not in DOCUMENTS:
        raise ApiError(ErrorCode.NOT_FOUND)
    return doc


@router.get("/v1/legal/{doc}")
async def legal_json(doc: str, request: Request, lang: str | None = Query(default=None, max_length=8),
                     c: Container = Depends(get_container)) -> dict:
    doc = _document(doc)
    language = _language(request, lang)
    title, sections = render(doc, language, identity(c))
    return {"schema_version": 1, "document": doc, "version": VERSIONS[doc],
            "language": language if language in DOCUMENTS[doc] else "en", "title": title, "sections": sections}


PAGE = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · Oltivra</title>
<style>
  body {{ margin:0; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; background:#FFFDF8;
         color:#1B2130; line-height:1.6; }}
  main {{ max-width:720px; margin:0 auto; padding:32px 20px 64px; }}
  h1 {{ font-size:28px; margin:0 0 4px; }}
  h2 {{ font-size:18px; margin:28px 0 8px; }}
  p {{ margin:0 0 12px; color:#3C4947; }}
  .meta {{ color:#636D7E; font-size:14px; margin-bottom:24px; }}
  .lang a {{ color:#006B5F; margin-right:12px; }}
</style>
</head>
<body>
<main>
<p class="lang"><a href="?lang=en">English</a><a href="?lang=tr">Türkçe</a></p>
<h1>{title}</h1>
<p class="meta">Version {version}</p>
{body}
</main>
</body>
</html>"""


@router.get("/legal/{doc}", response_class=HTMLResponse, include_in_schema=False)
async def legal_page(doc: str, request: Request, lang: str | None = Query(default=None, max_length=8),
                     c: Container = Depends(get_container)) -> HTMLResponse:
    doc = _document(doc)
    language = _language(request, lang)
    title, sections = render(doc, language, identity(c))
    body = "\n".join(
        f"<h2>{html.escape(str(s['heading']))}</h2>\n"
        + "\n".join(f"<p>{html.escape(str(p))}</p>" for p in s["paragraphs"])  # type: ignore[union-attr]
        for s in sections)
    page = PAGE.format(lang=language if language in DOCUMENTS[doc] else "en", title=html.escape(title),
                       version=VERSIONS[doc], body=body)
    return HTMLResponse(page, headers={"content-security-policy": "default-src 'none'; style-src 'unsafe-inline'",
                                       "cache-control": "public, max-age=3600"})
