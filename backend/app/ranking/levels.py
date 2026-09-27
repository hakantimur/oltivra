"""XP level curve (spec §7.1). The backend computes levels; clients only preview."""

from __future__ import annotations


def xp_to_start_level(level: int) -> int:
    if level <= 1:
        return 0
    return round(100 * (level - 1) ** 1.6)


def level_for_xp(total_xp: int) -> int:
    level = 1
    while xp_to_start_level(level + 1) <= total_xp:
        level += 1
    return level


def level_progress(total_xp: int) -> dict[str, int]:
    level = level_for_xp(total_xp)
    start = xp_to_start_level(level)
    nxt = xp_to_start_level(level + 1)
    return {"level": level, "level_start_xp": start, "next_level_xp": nxt, "xp_into_level": total_xp - start,
            "xp_for_level": nxt - start}
