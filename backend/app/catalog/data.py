"""Curated catalogs: avatars, frames, badges and reactions (spec §2.3, §5, §7.9).

Avatars are original abstract motifs rendered as vectors by the client (no uploads, no photos).
"""

from __future__ import annotations

from typing import Any

CATALOG_VERSION = 1

AVATARS: tuple[dict[str, Any], ...] = tuple(
    {"id": f"av_{i:03d}", "motif": motif, "bg": bg, "fg": fg, "accent": accent, "sort": i, "active": True}
    for i, (motif, bg, fg, accent) in enumerate([
        ("scholar", "#D5EFEA", "#16B8A6", "#0C4A43"),
        ("crescent", "#FFE3EC", "#AF2759", "#FFB1C3"),
        ("quarter", "#F7EEDC", "#CE9D1D", "#6B4F00"),
        ("eye_diamond", "#DDFBF4", "#16B8A6", "#1B2130"),
        ("person", "#E2E7FD", "#1B2130", "#636D7E"),
        ("star", "#FFF4DE", "#F4BF40", "#6B4F00"),
        ("arch", "#E9EDFF", "#16B8A6", "#F65F8E"),
        ("stripes", "#FFF0F5", "#AF2759", "#FFFFFF"),
        ("orbit", "#E2E7FD", "#006B5F", "#71F8E4"),
        ("prism", "#DDE2F7", "#1B2130", "#F65F8E"),
        ("lever", "#E8F8F5", "#16B8A6", "#F4BF40"),
        ("octagon", "#F1EDE4", "#6B4F00", "#FFC94A"),
    ], start=1)
)

# Bot-only avatars are drawn from the same curated catalog (no badge distinguishes bots, decision D3).

FRAMES: tuple[dict[str, Any], ...] = (
    {"id": "frame_none", "kind": "DEFAULT", "color": None, "names": {"en": "No frame", "tr": "Çerçeve yok"}},
    {"id": "frame_streak_5", "kind": "ACHIEVEMENT", "color": "#F65F8E",
     "names": {"en": "Hot Streak", "tr": "Seri Ateşi"}},
    {"id": "frame_crown", "kind": "ACHIEVEMENT", "color": "#FFC94A",
     "names": {"en": "Crowned", "tr": "Taçlı"}},
    {"id": "frame_diamond", "kind": "LEAGUE", "color": "#50DBC8",
     "names": {"en": "Diamond League", "tr": "Elmas Lig"}},
    {"id": "frame_legend", "kind": "LEAGUE", "color": "#AF2759",
     "names": {"en": "Legend League", "tr": "Efsane Lig"}},
    # Level rewards (playtest 2026-09-27): cosmetic frames unlocked by reaching a level.
    {"id": "frame_level_3", "kind": "LEVEL", "level": 3, "color": "#16B8A6",
     "names": {"en": "Spark", "tr": "Kıvılcım"}},
    {"id": "frame_level_5", "kind": "LEVEL", "level": 5, "color": "#5B7CFA",
     "names": {"en": "Rising Star", "tr": "Yükselen Yıldız"}},
    {"id": "frame_level_10", "kind": "LEVEL", "level": 10, "color": "#8E5CF6",
     "names": {"en": "Sharp Mind", "tr": "Keskin Zekâ"}},
    {"id": "frame_level_20", "kind": "LEVEL", "level": 20, "color": "#F28C28",
     "names": {"en": "Quiz Master", "tr": "Bilgi Ustası"}},
    {"id": "frame_level_30", "kind": "LEVEL", "level": 30, "color": "#1B2130",
     "names": {"en": "Grandmaster", "tr": "Büyük Usta"}},
)

# (level, frame id) milestones, ascending.
LEVEL_FRAMES: tuple[tuple[int, str], ...] = tuple(
    sorted((int(f["level"]), f["id"]) for f in FRAMES if f["kind"] == "LEVEL"))


def level_frames(level: int) -> set[str]:
    """Frames unlocked at or below ``level``."""
    return {frame_id for at, frame_id in LEVEL_FRAMES if level >= at}


def next_level_reward(level: int) -> dict[str, Any] | None:
    """The next level milestone above ``level`` and the frame it unlocks, or ``None`` past the last one."""
    for at, frame_id in LEVEL_FRAMES:
        if at > level:
            return {"level": at, "frame_id": frame_id}
    return None

BADGES: tuple[dict[str, Any], ...] = (
    {"id": "badge_first_quick_win", "names": {"en": "First Quick Win", "tr": "İlk Hızlı Zafer"}, "icon": "bolt"},
    {"id": "badge_10_ranked_quick_wins", "names": {"en": "10 Ranked Quick Wins", "tr": "10 Dereceli Zafer"},
     "icon": "military_tech"},
    {"id": "badge_5_ranked_streak", "names": {"en": "Five-Win Streak", "tr": "5 Galibiyet Serisi"},
     "icon": "local_fire_department"},
    {"id": "badge_first_crown", "names": {"en": "First Survival Crown", "tr": "İlk Hayatta Kalma Tacı"},
     "icon": "workspace_premium"},
    {"id": "badge_10_crowns", "names": {"en": "10 Survival Crowns", "tr": "10 Hayatta Kalma Tacı"},
     "icon": "crown"},
    {"id": "badge_geography_specialist", "names": {"en": "Geography Specialist", "tr": "Coğrafya Uzmanı"},
     "icon": "public"},
    {"id": "badge_science_specialist", "names": {"en": "Science Specialist", "tr": "Bilim Uzmanı"},
     "icon": "science"},
    {"id": "badge_diamond_league", "names": {"en": "Diamond League", "tr": "Elmas Lig"}, "icon": "diamond"},
    {"id": "badge_legend_league", "names": {"en": "Legend League", "tr": "Efsane Lig"}, "icon": "stars"},
)

REACTIONS: tuple[dict[str, Any], ...] = (
    {"id": "emoji_laugh", "kind": "EMOJI", "display": "😂", "labels": {"en": "Laugh", "tr": "Kahkaha"}},
    {"id": "emoji_fire", "kind": "EMOJI", "display": "🔥", "labels": {"en": "Fire", "tr": "Ateş"}},
    {"id": "emoji_clap", "kind": "EMOJI", "display": "👏", "labels": {"en": "Clap", "tr": "Alkış"}},
    {"id": "emoji_shock", "kind": "EMOJI", "display": "😱", "labels": {"en": "Shock", "tr": "Şok"}},
    {"id": "emoji_mindblown", "kind": "EMOJI", "display": "🤯", "labels": {"en": "Mind blown", "tr": "Aklım uçtu"}},
    {"id": "text_gg", "kind": "TEXT", "display": "GG!", "labels": {"en": "GG!", "tr": "İyi oyun!"}},
    {"id": "text_nice", "kind": "TEXT", "display": "Nice!", "labels": {"en": "Nice!", "tr": "Güzel!"}},
    {"id": "text_wow", "kind": "TEXT", "display": "Wow!", "labels": {"en": "Wow!", "tr": "Vay!"}},
    {"id": "text_oops", "kind": "TEXT", "display": "Oops!", "labels": {"en": "Oops!", "tr": "Hay aksi!"}},
    {"id": "text_come_on", "kind": "TEXT", "display": "Come on!", "labels": {"en": "Come on!", "tr": "Hadi!"}},
)

AVATAR_IDS = frozenset(a["id"] for a in AVATARS)
FRAME_IDS = frozenset(f["id"] for f in FRAMES)
BADGE_IDS = frozenset(b["id"] for b in BADGES)
REACTION_IDS = frozenset(r["id"] for r in REACTIONS)


async def seed_catalogs(store) -> None:
    """Write catalogs to their server-managed collections (idempotent)."""
    for avatar in AVATARS:
        await store.set(f"avatar_catalog/{avatar['id']}", {"schema_version": 1, "catalog_version": CATALOG_VERSION,
                                                           **avatar})
    for reaction in REACTIONS:
        await store.set(f"reaction_catalog/{reaction['id']}", {"schema_version": 1, "catalog_version": CATALOG_VERSION,
                                                               "active": True, **reaction})
    await store.set("catalog_meta/versions", {"schema_version": 1, "avatars": CATALOG_VERSION,
                                              "reactions": CATALOG_VERSION, "frames": CATALOG_VERSION,
                                              "badges": CATALOG_VERSION})
