"""League tiers (playtest 2026-09-27).

Leagues are weekly cohorts (``app.ranking.league_groups``): a player's tier only changes at the week rollover by
promotion or relegation. MMR stays server-only and is used for matchmaking and bot selection alone.
"""

from __future__ import annotations

from enum import StrEnum


class League(StrEnum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"
    DIAMOND = "DIAMOND"
    MASTER = "MASTER"
    LEGEND = "LEGEND"


TIERS: tuple[League, ...] = tuple(League)
START_TIER = League.BRONZE

# Only used to give match bots a plausible tier on their public card.
_BOT_TIER_BY_MMR: tuple[tuple[League, int], ...] = (
    (League.BRONZE, -10**9), (League.SILVER, 900), (League.GOLD, 1050), (League.PLATINUM, 1200),
    (League.DIAMOND, 1350), (League.MASTER, 1500), (League.LEGEND, 1700),
)


def tier_of(user: dict | None) -> League:
    value = (user or {}).get("league_tier")
    return League(value) if value in League.__members__ else START_TIER


def tier_index(tier: League | str) -> int:
    return TIERS.index(League(tier))


def promoted(tier: League | str) -> League:
    return TIERS[min(tier_index(tier) + 1, len(TIERS) - 1)]


def relegated(tier: League | str) -> League:
    return TIERS[max(tier_index(tier) - 1, 0)]


def bot_tier_for_mmr(mmr: int) -> League:
    current = League.BRONZE
    for league, lower in _BOT_TIER_BY_MMR:
        if mmr >= lower:
            current = league
    return current
