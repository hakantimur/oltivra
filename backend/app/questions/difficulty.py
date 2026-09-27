"""Empirical difficulty calibration (spec §3.4, §10.3).

Declared difficulty is used until a language/mode/version has at least ``min_attempts`` valid human attempts.
After that, the manifest for that language and mode places the question by its observed accuracy while keeping
the same Easy/Medium/Hard target bands.

- Valid attempts exclude Quick Battle players censored by an earlier correct answer (they had no opportunity).
- Survival and Synova observations weigh more than raw Quick Battle accuracy, which is biased by censoring.
- Bots never write statistics, so they never affect calibration.
"""

from __future__ import annotations

from typing import Any

MODES = ("QUICK", "SURVIVAL", "SYNOVA")
MODE_WEIGHTS = {"SURVIVAL": 1.0, "SYNOVA": 1.0, "QUICK": 0.5}


def valid_attempts(summary: dict[str, Any] | None) -> int:
    """Human observations that had a real opportunity to answer (answered or ran out of time)."""
    if not summary:
        return 0
    return int(summary.get("correct", 0)) + int(summary.get("wrong", 0)) + int(summary.get("no_answer", 0))


def accuracy(summary: dict[str, Any]) -> float:
    total = valid_attempts(summary)
    return int(summary.get("correct", 0)) / total if total else 0.0


def band_for(acc: float, easy_min: float, medium_min: float) -> str:
    if acc >= easy_min:
        return "EASY"
    if acc >= medium_min:
        return "MEDIUM"
    return "HARD"


def empirical_difficulty(mode: str, summaries: dict[str, dict[str, Any] | None], *, min_attempts: int,
                         easy_min: float, medium_min: float) -> str | None:
    """Band for ``mode`` from one language's per-mode summaries, or None while data is not yet reliable."""
    if valid_attempts(summaries.get(mode)) < min_attempts:
        return None
    weighted = total_weight = 0.0
    for other in MODES:
        summary = summaries.get(other)
        attempts = valid_attempts(summary)
        if not attempts:
            continue
        weight = MODE_WEIGHTS[other] * attempts
        weighted += accuracy(summary) * weight
        total_weight += weight
    return band_for(weighted / total_weight, easy_min, medium_min) if total_weight else None
