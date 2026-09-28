"""Adaptive bot difficulty (playtest 2026-09-28).

Quick battle rounds go to the first correct answer, so a player has to out-answer every bot at once; rosters
picked from MMR alone let casual players win only ~10% of their matches. Instead each player carries a hidden
``bot_level`` that rises after wins and falls after losses, and the bot roster is read from a ladder that ramps
from three BEGINNER bots to three EXPERT bots. With ``win_step`` : ``loss_step`` = 3 : 2 a player settles where
they win about 40% of bot matches, whatever their skill. The level never reaches the client (D3).
"""

from __future__ import annotations

from typing import Any

from app.common.server_config import BotConfig

# Quick battle rosters (3 bots) from easiest to hardest; larger rosters repeat the pattern.
LADDER: list[list[str]] = [
    ["BEGINNER", "BEGINNER", "BEGINNER"],
    ["BEGINNER", "BEGINNER", "NORMAL"],
    ["BEGINNER", "NORMAL", "NORMAL"],
    ["NORMAL", "NORMAL", "NORMAL"],
    ["NORMAL", "NORMAL", "STRONG"],
    ["NORMAL", "STRONG", "STRONG"],
    ["STRONG", "STRONG", "STRONG"],
    ["STRONG", "STRONG", "EXPERT"],
    ["STRONG", "EXPERT", "EXPERT"],
    ["EXPERT", "EXPERT", "EXPERT"],
]
MAX_LEVEL = float(len(LADDER) - 1)


def effective_level(user: dict[str, Any], cfg: BotConfig) -> float:
    """The ladder level a player's next bot match uses (warm-up cap and losing-streak relief applied)."""
    level = float(user.get("bot_level", cfg.start_level))
    if int(user.get("matches_completed", 0)) < cfg.warmup_matches:
        level = min(level, cfg.warmup_max_level)
    if int(user.get("bot_loss_streak", 0)) >= cfg.loss_streak_relief:
        level -= 1
    return max(0.0, min(MAX_LEVEL, level))


def roster_tiers(level: float, count: int) -> list[str]:
    """Bot tiers for ``count`` seats at a ladder level, easiest tiers first."""
    rung = LADDER[int(max(0.0, min(MAX_LEVEL, level)))]
    return [rung[slot % len(rung)] for slot in range(count)]


def after_match(user: dict[str, Any], *, mode: str, place: int | None, left: bool, players: int,
                cfg: BotConfig) -> dict[str, Any]:
    """New ``bot_level``/``bot_loss_streak`` after a completed match that had bots in it.

    Quick: a win steps up, anything else steps down. Survival (10 seats): a crown steps up, the top third
    holds, the rest step down by half. Leaving a match changes nothing, so quitting never eases the bots.
    """
    level = float(user.get("bot_level", cfg.start_level))
    streak = int(user.get("bot_loss_streak", 0))
    if left or place is None:
        return {"bot_level": level, "bot_loss_streak": streak}
    if place == 1:
        level, streak = level + cfg.win_step, 0
    elif mode == "SURVIVAL" and place <= max(1, players // 3):
        pass
    else:
        level -= cfg.loss_step / 2 if mode == "SURVIVAL" else cfg.loss_step
        streak += 1
    return {"bot_level": round(max(0.0, min(MAX_LEVEL, level)), 3), "bot_loss_streak": streak}
