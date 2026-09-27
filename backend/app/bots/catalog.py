"""Bot identity pool (spec §23.1). Bots are not Firebase Auth users and create no client connections.

Bot usernames are reserved in the same registry as human usernames. Per product decision D3 the client never
receives anything that distinguishes a bot; disclosure lives in Terms/Help.
"""

from __future__ import annotations

import random
from typing import Any

from app.catalog.data import AVATARS
from app.common.keys import Keyring
from app.common.server_config import GameConfig
from app.common.store.docstore import DocStore, Query
from app.ranking.leagues import display_league

_NAMES = [
    "ava_k", "kevin_q", "sora_7", "elena_z", "mira_lux", "theo_r", "nadia_v", "jonas_b", "lina_quiz", "omar_f",
    "yuki_t", "leo_mz", "zara_p", "ivan_d", "noor_s", "felix_o", "maya_rt", "kai_w", "ines_c", "raj_m",
    "tessa_l", "arlo_g", "amara_n", "hugo_e", "priya_k", "sven_h", "chloe_b", "mateo_r", "aisha_y", "lukas_p",
    "rosa_v", "emre_k", "sofia_d", "ben_trivia", "hana_j", "diego_s", "ella_fm", "karim_a", "june_o", "nils_q",
    "vera_x", "tariq_h", "lea_mn", "oscar_bt", "selin_a", "marco_v", "ida_w", "rafa_c",
]
_TIERS = ["BEGINNER", "NORMAL", "NORMAL", "STRONG", "STRONG", "EXPERT"]


def default_bots() -> list[dict[str, Any]]:
    bots = []
    for index, name in enumerate(_NAMES):
        tier = _TIERS[index % len(_TIERS)]
        bots.append({
            "schema_version": 1,
            "bot_id": f"bot_{index + 1:03d}",
            "username": name,
            "avatar_id": AVATARS[index % len(AVATARS)]["id"],
            "profile": tier,
            "active": True,
        })
    return bots


def bot_public_id(keys: Keyring, bot_id: str) -> str:
    # Same shape as human public IDs so clients cannot tell them apart (D3).
    return "p" + keys.username_hash.hexdigest(f"public-id:bot:{bot_id}")[:19]


def bot_public_profile(keys: Keyring, bot: dict[str, Any], config: GameConfig) -> dict[str, Any]:
    """Public card for a bot, indistinguishable in shape from a human public profile."""
    rng = random.Random(bot["bot_id"])
    mmr = config.bots.profiles[bot["profile"]].mmr
    return {
        "schema_version": 1,
        "public_id": bot_public_id(keys, bot["bot_id"]),
        "username_display": bot["username"],
        "avatar_id": bot["avatar_id"],
        "frame_id": "frame_none",
        "featured_badge_ids": [],
        "league": display_league(mmr, 5).value,
        "level": 4 + rng.randint(0, 20) + (mmr - 850) // 60,
        "quick_best_ranked_win_streak": rng.randint(0, 6),
        "survival_ranked_crowns_lifetime": rng.randint(0, 3),
        "quick_ranked_wins_lifetime": rng.randint(3, 60),
    }


async def seed_bots(store: DocStore, keys: Keyring, now_ms: int, config: GameConfig | None = None) -> None:
    config = config or GameConfig()
    for bot in default_bots():
        await store.set(f"bot_profiles/{bot['bot_id']}", bot)
        await store.set(f"username_registry/{bot['username'].lower()}", {
            "schema_version": 1, "state": "ACTIVE", "uid": f"bot:{bot['bot_id']}", "is_bot": True,
            "name": bot["username"].lower(),
            "updated_at_ms": now_ms,
        })
        profile = bot_public_profile(keys, bot, config)
        await store.set(f"public_profiles/{profile['public_id']}", profile)
        # Blocks/reports against a bot resolve like any player (D3); the server-side uid marks it as a bot.
        await store.set(f"public_ids/{profile['public_id']}", {"uid": f"bot:{bot['bot_id']}", "is_bot": True})


def tier_for_mmr(mmr: float) -> list[str]:
    if mmr < 900:
        return ["BEGINNER", "NORMAL"]
    if mmr < 1150:
        return ["NORMAL", "NORMAL", "BEGINNER", "STRONG"]
    if mmr < 1400:
        return ["STRONG", "NORMAL", "STRONG"]
    return ["EXPERT", "STRONG"]


class BotPool:
    def __init__(self, store: DocStore, keys: Keyring) -> None:
        self._store = store
        self._keys = keys

    async def active_bots(self) -> list[dict[str, Any]]:
        rows = [r.data for r in await self._store.query(Query("bot_profiles"))]
        return [b for b in (rows or default_bots()) if b.get("active", True)]

    def public_id(self, bot_id: str) -> str:
        return bot_public_id(self._keys, bot_id)

    async def pick(self, match_id: str, count: int, human_mmr_avg: float, exclude_names: set[str],
                   config: GameConfig) -> list[dict[str, Any]]:
        if count <= 0:
            return []
        rng = random.Random(int.from_bytes(self._keys.bot_plan.digest(f"roster:{match_id}")[:8], "big"))
        pool = [b for b in await self.active_bots() if b["username"].lower() not in exclude_names]
        rng.shuffle(pool)
        tiers = tier_for_mmr(human_mmr_avg)
        chosen: list[dict[str, Any]] = []
        for slot in range(count):
            wanted = tiers[slot % len(tiers)]
            match = next((b for b in pool if b["profile"] == wanted), None) or (pool[0] if pool else None)
            if match is None:
                break
            pool.remove(match)
            profile = config.bots.profiles[match["profile"]]
            chosen.append({**match, "mmr": profile.mmr, "profile_config": profile.model_dump()})
        return chosen
