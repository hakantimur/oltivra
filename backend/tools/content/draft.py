"""Large text-question banks: English drafts first, Turkish per category, then merge into the authored content.

Usage:
    python -m tools.content.draft check geography    # validate content/drafts/geography.en.json (English only)
    python -m tools.content.draft merge geography    # add content/drafts/geography.tr.json and move the rows into
                                                     # content/questions/geography.json (full EN+TR checks)

Draft rows use the authored-content shape with English only: ``question: {"en": ...}`` and options
``{"concept_id", "en"}``. The Turkish file maps each key to ``{"question": str, "options": {concept_id: str}}``.

Checks: competitive text rules (spec §9), taxonomy, relevance >= 4, English Wikipedia source, key uniqueness across
the whole bank, the 40/40/20 EASY/MEDIUM/HARD mix (reported), and near-duplicates against every other question in
the bank (seed, authored content and all drafts). Similarity uses the admin duplicate detector's hashed trigram
vectors through an inverted index, so thousands of questions compare in seconds.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from app.admin.duplicates import embed
from app.questions.models import OptionText, QuestionTranslation, normalise_text, validate_competitive_text
from app.questions.seed import load_seed_items
from app.questions.taxonomy import CATEGORY_IDS, is_valid_subcategory

BACKEND = Path(__file__).resolve().parents[2]
CONTENT_DIR = BACKEND / "content" / "questions"
DRAFT_DIR = BACKEND / "content" / "drafts"
ERROR_SIMILARITY = 0.86
WARN_SIMILARITY = 0.6
IDENTICAL_SIMILARITY = 0.95
TARGET_MIX = {"EASY": 0.4, "MEDIUM": 0.4, "HARD": 0.2}


def _read(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def _write(path: Path, rows: list[dict] | dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(rows, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))


def draft_rows(category: str) -> list[dict]:
    return _read(DRAFT_DIR / f"{category}.en.json")


def _answer(row: dict) -> str:
    text = next((o["en"] for o in row["options"] if o["concept_id"] == row.get("correct")), "")
    return normalise_text(text)


def bank() -> list[tuple[str, str, str]]:
    """(key, English question, normalised English answer) for every question: seed, content and all drafts."""
    rows = list(load_seed_items())
    for path in sorted(CONTENT_DIR.glob("*.json")):
        rows += _read(path)
    for path in sorted(DRAFT_DIR.glob("*.en.json")):
        rows += _read(path)
    return [(r["key"], r["question"]["en"], _answer(r)) for r in rows]


def row_problems(row: dict, languages: tuple[str, ...]) -> list[str]:
    key = row.get("key", "?")
    out: list[str] = []
    if row.get("category_id") not in CATEGORY_IDS:
        out.append(f"{key}: unknown category")
    elif not is_valid_subcategory(row["category_id"], row.get("subcategory_id", "")):
        out.append(f"{key}: unknown subcategory {row.get('subcategory_id')}")
    if row.get("difficulty") not in TARGET_MIX:
        out.append(f"{key}: difficulty must be EASY/MEDIUM/HARD")
    if int(row.get("global_relevance_score", 0)) < 4:
        out.append(f"{key}: global relevance below 4")
    if not str(row.get("source", "")).startswith("https://en.wikipedia.org/wiki/"):
        out.append(f"{key}: source must be an English Wikipedia URL")
    for lang in languages:
        try:
            translation = QuestionTranslation(
                question_group_id="g", question_version=1, language=lang, question_text=row["question"][lang],
                options=[OptionText(concept_id=o["concept_id"], text=o[lang]) for o in row["options"]])
        except Exception as exc:  # noqa: BLE001 - surface schema errors as content problems
            out.append(f"{key}: {lang} invalid: {exc}")
            continue
        out += [f"{key}: {lang} {p}" for p in validate_competitive_text(translation, row.get("correct"))]
    correct = next((o["en"] for o in row.get("options", []) if o["concept_id"] == row.get("correct")), "")
    if correct and len(correct) > 3 and correct.lower() in row["question"]["en"].lower():
        out.append(f"{key}: correct answer text appears in the question")
    return out


def near_duplicates(focus: set[str], rows: list[tuple[str, str, str]]) -> tuple[list[str], list[str]]:
    """Same fact asked twice: similar wording *and* the same correct answer (templated questions such as "What is
    the capital of X?" share wording but not answers). Near-identical wording is an error regardless."""
    vectors = {key: embed(text) for key, text, _ in rows}
    answers = {key: answer for key, _, answer in rows}
    index: dict[int, list[tuple[str, float]]] = defaultdict(list)
    for key, vector in vectors.items():
        for dim, weight in vector.items():
            index[dim].append((key, weight))
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[tuple[str, str]] = set()
    for key in sorted(focus):
        scores: dict[str, float] = defaultdict(float)
        for dim, weight in vectors[key].items():
            for other, w in index[dim]:
                if other != key:
                    scores[other] += weight * w
        for other, score in scores.items():
            pair = tuple(sorted((key, other)))
            same_answer = answers[key] == answers[other]
            if pair in seen or score < (WARN_SIMILARITY if same_answer else IDENTICAL_SIMILARITY):
                continue
            seen.add(pair)
            label = f"{pair[0]} / {pair[1]}: {score:.2f}{' same answer' if same_answer else ''}"
            (errors if score >= ERROR_SIMILARITY else warnings).append(label)
    return errors, warnings


def report(rows: list[dict], languages: tuple[str, ...]) -> dict:
    all_rows = bank()
    keys = Counter(k for k, *_ in all_rows)
    errors = [f"{k}: duplicate key" for k, n in keys.items() if n > 1]
    for row in rows:
        errors += row_problems(row, languages)
    dup_errors, dup_warnings = near_duplicates({r["key"] for r in rows}, all_rows)
    mix = Counter(r.get("difficulty") for r in rows)
    subs = Counter(r.get("subcategory_id") for r in rows)
    return {"checked": len(rows), "mix": {d: mix.get(d, 0) for d in TARGET_MIX},
            "subcategories": dict(sorted(subs.items())), "errors": errors + dup_errors, "warnings": dup_warnings}


def merge(category: str) -> dict:
    drafts = draft_rows(category)
    tr = json.loads((DRAFT_DIR / f"{category}.tr.json").read_text(encoding="utf-8"))
    missing = [r["key"] for r in drafts if r["key"] not in tr]
    if missing:
        return {"errors": [f"{k}: Turkish translation missing" for k in missing]}
    merged = []
    for row in drafts:
        t = tr[row["key"]]
        options = [{**o, "tr": t["options"][o["concept_id"]]} for o in row["options"]]
        merged.append({**row, "question": {"en": row["question"]["en"], "tr": t["question"]}, "options": options})
    result = report(merged, ("en", "tr"))
    if result["errors"]:
        return result
    content = CONTENT_DIR / f"{category}.json"
    _write(content, _read(content) + merged)
    (DRAFT_DIR / f"{category}.en.json").unlink()
    (DRAFT_DIR / f"{category}.tr.json").unlink()
    return {**result, "merged": len(merged), "total": len(_read(content))}


def main() -> None:
    command, category = sys.argv[1], sys.argv[2]
    result = report(draft_rows(category), ("en",)) if command == "check" else merge(category)
    print(json.dumps(result, indent=1, ensure_ascii=False))
    sys.exit(1 if result.get("errors") else 0)


if __name__ == "__main__":
    main()
