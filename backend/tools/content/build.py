"""Build image-question seed files from authored content (adapted from Synova's curiosity_content/build.js).

Usage:
    python -m tools.content.build geography          # one category
    python -m tools.content.build --all

Reads ``content/questions/<category>.json`` (authored rows), resolves each row's picked Commons candidate from
``tools/content/work/refined/<topic>.json``, downloads it once, converts it to WebP (<=1024 px, <=200 KB, spec §9.1),
checks that the Wikipedia source page exists, and writes ``seed/curated/<category>.json`` plus
``seed/media/<category>/<key>.webp``. The correct answer's display position is irrelevant: every player gets an
independently shuffled option order (spec §3.6).
"""

from __future__ import annotations

import io
import json
import sys
import urllib.parse
from pathlib import Path

from PIL import Image

from tools.content.commons import WORK, fetch

BACKEND = Path(__file__).resolve().parents[2]
CONTENT_DIR = BACKEND / "content" / "questions"
SEED_OUT = BACKEND / "seed" / "curated"
MEDIA_OUT = BACKEND / "seed" / "media"
MAX_DIMENSION = 1024
MAX_BYTES = 200_000


def to_webp(data: bytes) -> tuple[bytes, int, int]:
    img = Image.open(io.BytesIO(data))
    img = img.convert("RGB")
    img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)
    for quality in (82, 76, 70, 64, 58, 50):
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=quality, method=6)
        if buf.tell() <= MAX_BYTES:
            return buf.getvalue(), img.width, img.height
    raise ValueError("cannot fit image under the preferred size")


def wikipedia_exists(url: str) -> bool:
    title = urllib.parse.unquote(url.rsplit("/wiki/", 1)[-1])
    api = ("https://en.wikipedia.org/w/api.php?action=query&format=json&redirects=1&titles="
           + urllib.parse.quote(title))
    pages = json.loads(fetch(api)).get("query", {}).get("pages", {})
    return bool(pages) and "-1" not in pages


def copyright_status(license_name: str) -> str:
    lowered = license_name.lower()
    return "PUBLIC_DOMAIN" if lowered.startswith(("cc0", "public domain", "pd")) else "LICENSED"


def build_category(category: str) -> list[str]:
    rows = json.loads((CONTENT_DIR / f"{category}.json").read_text(encoding="utf-8"))
    problems: list[str] = []
    items = []
    for row in rows:
        key = row["key"]
        if not wikipedia_exists(row["source"]):
            problems.append(f"{key}: Wikipedia page not found: {row['source']}")
        pick = row.get("image")
        if pick is None:  # text-only question
            items.append(dict(row))
            continue
        refined = json.loads((WORK / "refined" / f"{pick['refined']}.json").read_text(encoding="utf-8"))
        candidate = refined["candidates"][pick["index"]]
        target = MEDIA_OUT / category / f"{key}.webp"
        if not target.exists():
            data, _, _ = to_webp(fetch(candidate["thumb"]))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        credit = f"{candidate['author']} / Wikimedia Commons, {candidate['license']}"
        item = {k: v for k, v in row.items() if k != "image"}
        item["media"] = {
            "file": f"{category}/{key}.webp",
            "alt_text": pick["alt_text"],
            "source": candidate["page_url"],
            "author": candidate["author"][:120],
            "license": candidate["license"],
            "attribution": credit[:300],
            "copyright_status": copyright_status(candidate["license"]),
        }
        items.append(item)
    SEED_OUT.mkdir(parents=True, exist_ok=True)
    (SEED_OUT / f"{category}.json").write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n",
                                               encoding="utf-8")
    return problems


def main() -> None:
    categories = ([p.stem for p in sorted(CONTENT_DIR.glob("*.json"))] if sys.argv[1:] == ["--all"]
                  else sys.argv[1:])
    problems = [p for c in categories for p in build_category(c)]
    print(json.dumps({"built": categories, "problems": problems}, indent=1, ensure_ascii=False))
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
