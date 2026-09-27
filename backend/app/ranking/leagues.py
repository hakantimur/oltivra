"""Leagues from server-only MMR (spec §7.3). Clients see league + abstract progress, never raw MMR."""

from __future__ import annotations

from enum import StrEnum


class League(StrEnum):
    UNRANKED = "UNRANKED"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"
    DIAMOND = "DIAMOND"
    MASTER = "MASTER"
    LEGEND = "LEGEND"


# (league, inclusive lower bound)
THRESHOLDS: tuple[tuple[League, int], ...] = (
    (League.BRONZE, -10**9),
    (League.SILVER, 900),
    (League.GOLD, 1050),
    (League.PLATINUM, 1200),
    (League.DIAMOND, 1350),
    (League.MASTER, 1500),
    (League.LEGEND, 1700),
)


def league_for_mmr(mmr: int) -> League:
    current = League.BRONZE
    for league, lower in THRESHOLDS:
        if mmr >= lower:
            current = league
    return current


def display_league(mmr: int, placement_matches_completed: int, placement_required: int = 5) -> League:
    if placement_matches_completed < placement_required:
        return League.UNRANKED
    return league_for_mmr(mmr)


def league_progress(mmr: int, placement_matches_completed: int, placement_required: int = 5) -> dict:
    """Abstract 0..1 progress toward the next league; no raw MMR is returned."""
    league = display_league(mmr, placement_matches_completed, placement_required)
    if league == League.UNRANKED:
        return {"league": league.value, "progress": round(placement_matches_completed / placement_required, 3),
                "next_league": None, "placement_matches_remaining": placement_required - placement_matches_completed}
    bounds = [lower for _, lower in THRESHOLDS]
    names = [lg for lg, _ in THRESHOLDS]
    index = names.index(league)
    if index == len(names) - 1:
        return {"league": league.value, "progress": 1.0, "next_league": None, "placement_matches_remaining": 0}
    low = bounds[index] if index > 0 else 750
    high = bounds[index + 1]
    progress = min(1.0, max(0.0, (mmr - low) / (high - low)))
    return {"league": league.value, "progress": round(progress, 3), "next_league": names[index + 1].value,
            "placement_matches_remaining": 0}
