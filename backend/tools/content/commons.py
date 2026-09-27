"""Wikimedia Commons image candidates for image questions (adapted from Synova's curiosity_content/refine.js).

Usage:
    python -m tools.content.commons '[["topic_id", "search terms"], ["topic2", "terms"]]'

For every topic: searches Commons bitmaps, keeps freely licensed candidates (CC0 / public domain / CC BY /
CC BY-SA, no NC/ND) that are at least 1000x600, writes ``work/refined/<topic>.json`` and 330px previews, and
builds one labelled contact sheet ``work/sheets/<topic>.png`` so a reviewer can pick a candidate index by eye.
"""

from __future__ import annotations

import html
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

WORK = Path(__file__).resolve().parent / "work"
API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "OltivraContentTool/1.0 (contact: support@noriloop.net)"
LICENSE_OK = re.compile(r"^(cc0|public domain|pd|cc[- ]by(?:[- ]sa)?[- ]\d(\.\d)?|cc[- ]by(?:[- ]sa)?)", re.I)
LICENSE_BAD = re.compile(r"nc|nd|fair use|gfdl only|copyrighted", re.I)
MAX_CANDIDATES = 6
PREVIEW_WIDTH = 330


def fetch(url: str, timeout: float = 30.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except Exception:  # noqa: BLE001 - network hiccups and 429s: back off and retry
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def plain(value: str | None) -> str:
    """Commons extmetadata values are HTML fragments."""
    text = re.sub(r"<[^>]+>", "", value or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def search(query: str) -> list[dict]:
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": "6",
        "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": "25", "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata", "iiurlwidth": "1280",
    }
    data = json.loads(fetch(f"{API}?{urllib.parse.urlencode(params)}"))
    pages = sorted((data.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    out: list[dict] = []
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        license_name = plain((meta.get("LicenseShortName") or {}).get("value"))
        if not LICENSE_OK.match(license_name) or LICENSE_BAD.search(license_name):
            continue
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        if info.get("width", 0) < 1000 or info.get("height", 0) < 600:
            continue
        out.append({
            "title": page["title"],
            "page_url": info.get("descriptionurl"),
            "thumb": info.get("thumburl"),
            "width": info.get("width"),
            "height": info.get("height"),
            "license": license_name,
            "author": plain((meta.get("Artist") or {}).get("value")) or "Unknown author",
            "attribution_required": plain((meta.get("AttributionRequired") or {}).get("value")) != "false",
        })
        if len(out) >= MAX_CANDIDATES:
            break
    return out


def contact_sheet(topic: str, previews: list[Image.Image]) -> Path:
    tile_w, tile_h, cols = 330, 250, 3
    rows = max(1, -(-len(previews) // cols))
    sheet = Image.new("RGB", (cols * tile_w, rows * tile_h), "white")
    draw = ImageDraw.Draw(sheet)
    for i, img in enumerate(previews):
        img = img.copy()
        img.thumbnail((tile_w - 6, tile_h - 6))
        x, y = (i % cols) * tile_w, (i // cols) * tile_h
        sheet.paste(img, (x + 3, y + 3))
        draw.rectangle([x + 3, y + 3, x + 33, y + 29], fill="black")
        draw.text((x + 12, y + 8), str(i), fill="white")
    path = WORK / "sheets" / f"{topic}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)
    return path


def refine(topic: str, query: str) -> dict:
    candidates = search(query)
    previews: list[Image.Image] = []
    for candidate in candidates:
        thumb = candidate["thumb"]
        small = re.sub(r"/\d+px-", f"/{PREVIEW_WIDTH}px-", thumb) if thumb else None
        try:
            previews.append(Image.open(io.BytesIO(fetch(small or thumb))).convert("RGB"))
        except Exception:  # noqa: BLE001
            previews.append(Image.new("RGB", (PREVIEW_WIDTH, 200), "grey"))
    refined = {"topic": topic, "query": query, "candidates": candidates}
    path = WORK / "refined" / f"{topic}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(refined, indent=1, ensure_ascii=False), encoding="utf-8")
    sheet = contact_sheet(topic, previews) if previews else None
    return {"topic": topic, "candidates": len(candidates), "sheet": str(sheet) if sheet else None}


def main() -> None:
    topics = json.loads(sys.argv[1])
    for topic, query in topics:
        print(json.dumps(refine(topic, query), ensure_ascii=False))


if __name__ == "__main__":
    main()
