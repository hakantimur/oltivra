"""Validate authored questions (image optional) and find duplicates (after Synova's check_content.js / dedupe.js).

Usage:
    python -m tools.content.check                  # all authored categories
    python -m tools.content.check geography        # one file, still compared against every other file

Errors (exit 1): competitive text rules (spec §9), unknown category/subcategory, relevance < 4, missing
translations/alt text, not 4 options, same Commons image used twice, near-duplicate question text across the
whole bank (semantic similarity >= 0.86, the server's default threshold). Warnings: same Wikipedia source,
similarity >= 0.6, the correct answer text appearing in the question or alt text.
"""

from __future__ import annotations

import json
import sys
from itertools import combinations
from pathlib import Path

from app.admin.duplicates import cosine, embed
from app.questions.models import OptionText, QuestionTranslation, validate_competitive_text
from app.questions.seed import SEED_LANGUAGES, load_seed_items
from app.questions.taxonomy import CATEGORY_IDS, is_valid_subcategory

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content" / "questions"
ERROR_SIMILARITY = 0.86
WARN_SIMILARITY = 0.6


def load_rows(category: str | None = None) -> list[dict]:
    files = [CONTENT_DIR / f"{category}.json"] if category else sorted(CONTENT_DIR.glob("*.json"))
    rows: list[dict] = []
    for path in files:
        rows.extend(json.loads(path.read_text(encoding="utf-8")))
    return rows


def row_problems(row: dict) -> list[str]:
    key = row.get("key", "?")
    out: list[str] = []
    if row.get("category_id") not in CATEGORY_IDS:
        out.append(f"{key}: unknown category")
    elif not is_valid_subcategory(row["category_id"], row.get("subcategory_id", "")):
        out.append(f"{key}: unknown subcategory {row.get('subcategory_id')}")
    if row.get("difficulty") not in ("EASY", "MEDIUM", "HARD"):
        out.append(f"{key}: difficulty must be EASY/MEDIUM/HARD")
    if int(row.get("global_relevance_score", 0)) < 4:
        out.append(f"{key}: global relevance below 4")
    if not str(row.get("source", "")).startswith("https://en.wikipedia.org/wiki/"):
        out.append(f"{key}: source must be an English Wikipedia URL")
    if len(row.get("options", [])) != 4:
        out.append(f"{key}: exactly 4 options required")
    image = row.get("image")  # optional: not every trivia question needs a picture
    if image is not None and (not image.get("refined") or not isinstance(image.get("index"), int)):
        out.append(f"{key}: image.refined / image.index missing")
    for lang in SEED_LANGUAGES:
        if lang not in row.get("question", {}) or (image is not None and lang not in (image.get("alt_text") or {})):
            out.append(f"{key}: {lang} question/alt text missing")
            continue
        try:
            translation = QuestionTranslation(
                question_group_id="g", question_version=1, language=lang, question_text=row["question"][lang],
                options=[OptionText(concept_id=o["concept_id"], text=o[lang]) for o in row["options"]])
        except Exception as exc:  # noqa: BLE001 - surface schema errors as content problems
            out.append(f"{key}: {lang} invalid: {exc}")
            continue
        out += [f"{key}: {lang} {p}" for p in validate_competitive_text(translation, row.get("correct"))]
    return out


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    rows = load_rows()
    focus = {r["key"] for r in load_rows(only)} if only else {r["key"] for r in rows}
    errors: list[str] = []
    warnings: list[str] = []
    keys = [r["key"] for r in rows]
    errors += [f"{k}: duplicate key" for k in {k for k in keys if keys.count(k) > 1}]
    for row in rows:
        if row["key"] in focus:
            errors += row_problems(row)
            correct = next((o["en"] for o in row["options"] if o["concept_id"] == row.get("correct")), "")
            alt = (row.get("image") or {}).get("alt_text", {}).get("en", "")
            if correct and (correct.lower() in row["question"]["en"].lower() or correct.lower() in alt.lower()):
                warnings.append(f"{row['key']}: correct answer text appears in the question or alt text")
    # Bank-wide comparisons: image questions against each other and against the text seed pool.
    bank = [(r["key"], r["question"]["en"], r.get("source"), (r.get("image") or {}).get("refined"),
             (r.get("image") or {}).get("index")) for r in rows]
    bank += [(i["key"], i["question"]["en"], i.get("source"), None, None) for i in load_seed_items()]
    vectors = {k: embed(q) for k, q, *_ in bank}
    for (k1, _q1, s1, r1, i1), (k2, _q2, s2, r2, i2) in combinations(bank, 2):
        if k1 not in focus and k2 not in focus:
            continue
        if r1 and r1 == r2 and i1 == i2:
            errors.append(f"{k1} / {k2}: same image")
        score = cosine(vectors[k1], vectors[k2])
        if score >= ERROR_SIMILARITY:
            errors.append(f"{k1} / {k2}: near-duplicate question ({score:.2f})")
        elif score >= WARN_SIMILARITY:
            warnings.append(f"{k1} / {k2}: similar question ({score:.2f})")
        if s1 and s1 == s2 and r1 and r2:
            warnings.append(f"{k1} / {k2}: same Wikipedia source")
    print(json.dumps({"checked": len(focus), "errors": errors, "warnings": warnings}, indent=1,
                     ensure_ascii=False))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
