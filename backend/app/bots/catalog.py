"""Bot identity pool (spec §23.1). Bots are not Firebase Auth users and create no client connections.

Bot usernames are reserved in the same registry as human usernames. Per product decision D3 the client never
receives anything that distinguishes a bot; disclosure lives in Terms/Help.
"""

from __future__ import annotations

import random
from typing import Any

from app.bots.difficulty import roster_tiers
from app.catalog.data import AVATARS
from app.common.keys import Keyring
from app.common.server_config import GameConfig
from app.common.store.docstore import DocStore, Query
from app.ranking.leagues import bot_tier_for_mmr

_NAMES = [
    "ava_k", "kevin_q", "sora_7", "elena_z", "mira_lux", "theo_r", "nadia_v", "jonas_b", "lina_quiz", "omar_f",
    "yuki_t", "leo_mz", "zara_p", "ivan_d", "noor_s", "felix_o", "maya_rt", "kai_w", "ines_c", "raj_m",
    "tessa_l", "arlo_g", "amara_n", "hugo_e", "priya_k", "sven_h", "chloe_b", "mateo_r", "aisha_y", "lukas_p",
    "rosa_v", "emre_k", "sofia_d", "ben_trivia", "hana_j", "diego_s", "ella_fm", "karim_a", "june_o", "nils_q",
    "vera_x", "tariq_h", "lea_mn", "oscar_bt", "selin_a", "marco_v", "ida_w", "rafa_c",
    # Added 2026-09-28 (pool 48 -> 150): frequent repeats of the same few names read as fake.
    "burak_34", "zeynep_ay", "mert_kaya", "elif_nur", "can_bey", "ayse_tr", "deniz_k", "ozan_06", "ece_bilgi",
    "kerem_s", "irem_y", "baris_42", "gizem_t", "onur_d", "melis_a", "tolga_35", "cansu_k", "arda_16",
    "nazli_e", "umut_b", "sena_07", "yigit_h", "damla_c", "efe_quiz", "busra_m", "serkan_61", "ceren_o",
    "kaan_u", "ebru_l", "halil_27", "tugba_s", "furkan_z", "dilara_g", "volkan_p", "pinar_e", "berk_01",
    "asli_r", "hakki_55", "sibel_n", "cem_ozt", "gamze_d", "alper_k", "yasemin_b", "emir_t", "beren_a",
    "sinan_09", "nehir_s", "orhan_bey", "ilayda_k", "batu_33", "merve_c", "koray_f", "duygu_y", "taylan_m",
    "nisa_22", "ilker_o",
    "liam_ro", "emma_jk", "noah_24", "olivia_p", "lucas_br", "mia_quiz", "ethan_w", "isla_m", "mason_t",
    "zoe_lang", "pablo_gs", "lucia_mr", "mateus_s", "ana_clara", "giulia_b", "luca_ft", "marie_dl",
    "paul_ln", "anna_kw", "jan_nowak", "sara_ali", "yusuf_k", "fatima_z", "hiro_s", "mei_ling", "arjun_v",
    "ananya_r", "kofi_a", "ama_ns", "dmitri_v", "katya_s", "erik_lund", "freya_n", "lars_o", "nina_vk",
    "tom_hx", "grace_e", "sam_19", "ruby_kt", "max_power", "lily_ann", "jake_mp", "aylin_ko", "selim_88", "clara_vt",
    "diana_ro",
]
# Tier mix weighted towards the easy end of the ladder (new and casual players meet those rosters most).
_TIER_CYCLE = ["BEGINNER", "NORMAL", "BEGINNER", "STRONG", "NORMAL", "BEGINNER", "NORMAL", "EXPERT", "BEGINNER",
               "STRONG", "NORMAL", "BEGINNER", "STRONG", "NORMAL", "EXPERT"]
_TIER_ORDER = ["BEGINNER", "NORMAL", "STRONG", "EXPERT"]


def default_bots() -> list[dict[str, Any]]:
    bots = []
    for index, name in enumerate(_NAMES):
        tier = _TIER_CYCLE[index % len(_TIER_CYCLE)]
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
        "league": bot_tier_for_mmr(mmr).value,
        "level": 4 + rng.randint(0, 20) + (mmr - 850) // 60,
        "quick_best_ranked_win_streak": rng.randint(0, 6),
        "survival_ranked_crowns_lifetime": rng.randint(0, 3),
        "quick_ranked_wins_lifetime": rng.randint(3, 60),
    }


async def seed_bots(store: DocStore, keys: Keyring, now_ms: int, config: GameConfig | None = None) -> None:
    config = config or GameConfig()
    for bot in default_bots():
        registered = await store.get(f"username_registry/{bot['username'].lower()}")
        if registered and registered.get("uid") != f"bot:{bot['bot_id']}":
            # A human (or another bot) already owns the name: never take it over, keep this bot out of play.
            await store.set(f"bot_profiles/{bot['bot_id']}", {**bot, "active": False})
            continue
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


class BotPool:
    def __init__(self, store: DocStore, keys: Keyring) -> None:
        self._store = store
        self._keys = keys

    async def active_bots(self) -> list[dict[str, Any]]:
        rows = [r.data for r in await self._store.query(Query("bot_profiles"))]
        return [b for b in (rows or default_bots()) if b.get("active", True)]

    def public_id(self, bot_id: str) -> str:
        return bot_public_id(self._keys, bot_id)

    async def pick(self, match_id: str, count: int, levels: list[float], exclude_names: set[str],
                   config: GameConfig) -> list[dict[str, Any]]:
        """Bots for ``count`` seats at the average ladder level of the human seats (app.bots.difficulty)."""
        if count <= 0:
            return []
        rng = random.Random(int.from_bytes(self._keys.bot_plan.digest(f"roster:{match_id}")[:8], "big"))
        pool = [b for b in await self.active_bots() if b["username"].lower() not in exclude_names]
        rng.shuffle(pool)
        level = sum(levels) / len(levels) if levels else config.bots.start_level
        chosen: list[dict[str, Any]] = []
        for wanted in roster_tiers(level, count):
            # Closest tier when the wanted one ran out (ties go to the easier tier).
            rank = _TIER_ORDER.index(wanted)
            match = min(pool, key=lambda b: (abs(_TIER_ORDER.index(b["profile"]) - rank),
                                             _TIER_ORDER.index(b["profile"])), default=None)
            if match is None:
                break
            pool.remove(match)
            profile = config.bots.profiles[match["profile"]]
            chosen.append({**match, "mmr": profile.mmr, "profile_config": profile.model_dump()})
        return chosen
