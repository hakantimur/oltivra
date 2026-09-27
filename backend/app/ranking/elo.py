"""Pairwise Elo for multi-player matches (spec §7.3).

Ratings come only from immutable ``pre_match_mmr`` snapshots. Bots have fixed MMR, participate in expected
outcomes of ranked-eligible matches, and never change.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Seat:
    key: str
    pre_match_mmr: float
    place: int
    is_bot: bool = False


def expected(rating_i: float, rating_j: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_j - rating_i) / 400.0))


def actual(place_i: int, place_j: int) -> float:
    if place_i < place_j:
        return 1.0
    if place_i == place_j:
        return 0.5
    return 0.0


def rating_deltas(seats: list[Seat], base_k: float, provisional: dict[str, bool] | None = None,
                  provisional_multiplier: float = 1.5) -> dict[str, int]:
    """``round(K * average(actual - expected))`` for every human seat; bots are not returned."""
    provisional = provisional or {}
    deltas: dict[str, int] = {}
    for seat in seats:
        if seat.is_bot:
            continue
        opponents = [o for o in seats if o.key != seat.key]
        if not opponents:
            deltas[seat.key] = 0
            continue
        diff = sum(actual(seat.place, o.place) - expected(seat.pre_match_mmr, o.pre_match_mmr) for o in opponents)
        k = base_k * (provisional_multiplier if provisional.get(seat.key) else 1.0)
        deltas[seat.key] = round(k * diff / len(opponents))
    return deltas
