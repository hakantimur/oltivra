"""Question-bank draft checks: duplicates need similar wording *and* the same answer."""

from __future__ import annotations

from tools.content.draft import near_duplicates, row_problems


def _row(key: str, question: str, correct: str, others: list[str]) -> dict:
    options = [{"concept_id": t.lower().replace(" ", "_"), "en": t} for t in [correct, *others]]
    return {"key": key, "category_id": "geography", "subcategory_id": "capitals", "difficulty": "EASY",
            "global_relevance_score": 5, "question": {"en": question}, "options": options,
            "correct": options[0]["concept_id"], "source": "https://en.wikipedia.org/wiki/Rome"}


def test_templated_questions_with_different_answers_are_not_duplicates():
    rows = [("a", "What is the capital city of Italy?", "rome"), ("b", "What is the capital city of Spain?", "madrid")]
    errors, warnings = near_duplicates({"a", "b"}, rows)
    assert errors == [] and warnings == []


def test_same_fact_reworded_is_flagged():
    rows = [("a", "In which city does the Colosseum stand?", "rome"),
            ("b", "In which city does the Colosseum stand today?", "rome")]
    errors, _ = near_duplicates({"a"}, rows)
    assert errors == ["a / b: 0.97 same answer"] or errors[0].startswith("a / b:")


def test_row_rules_cover_english_only_drafts():
    assert row_problems(_row("a", "What is the capital city of Italy?", "Rome", ["Milan", "Venice", "Naples"]),
                        ("en",)) == []
    bad = _row("b", "Which city is Rome?", "Rome", ["Milan", "Venice", "Naples"])
    assert any("correct answer text appears" in p for p in row_problems(bad, ("en",)))
