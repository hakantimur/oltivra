"""Base match XP (spec §7.1). XP is permanent and never decreases; reward bonus XP is handled elsewhere."""

from __future__ import annotations

from typing import Any

PARTICIPATION_XP = 10
QUICK_PLACEMENT_BONUS = {1: 40, 2: 25, 3: 15, 4: 10}
SURVIVAL_PLACEMENT_BONUS = {1: 60, 2: 40, 3: 30, 4: 20, 5: 15, 6: 10, 7: 8, 8: 6, 9: 4, 10: 2}
SURVIVAL_ROUND_XP = 8


def quick_base_xp(final_normal_score: int, place: int | None, left: bool) -> int:
    bonus = 0 if left or place is None else QUICK_PLACEMENT_BONUS.get(place, 0)
    return PARTICIPATION_XP + max(final_normal_score, 0) + bonus


def survival_base_xp(completed_rounds: int, place: int | None, left: bool) -> int:
    bonus = 0 if left or place is None else SURVIVAL_PLACEMENT_BONUS.get(place, 0)
    return PARTICIPATION_XP + SURVIVAL_ROUND_XP * completed_rounds + bonus


def completed_survival_rounds(round_log: list[dict[str, Any]], pid: str) -> int:
    """Rounds the player lived through that reached a normal/tiebreak resolution with an accepted answer.

    A zero-answer rescue round does not generate extra round XP (spec §7.1).
    """
    count = 0
    for entry in round_log:
        if pid not in (entry.get("eligible") or []):
            continue
        if entry.get("resolution") in (None, "NO_ANSWERS"):
            continue
        if not entry.get("answers"):
            continue
        if pid in (entry.get("eliminated") or []):
            continue
        count += 1
    return count
