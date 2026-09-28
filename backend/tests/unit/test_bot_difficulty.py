"""Adaptive bot rosters and the expanded bot pool (playtest 2026-09-28)."""

from __future__ import annotations

import asyncio
from collections import Counter

from app.bots.catalog import _NAMES, BotPool, default_bots, seed_bots
from app.bots.difficulty import LADDER, MAX_LEVEL, after_match, effective_level, roster_tiers
from app.common.keys import Keyring
from app.common.server_config import BotConfig, GameConfig
from app.common.store.memory_docstore import MemoryDocStore
from app.usernames.rules import check_username
from tests.conftest import make_settings

CFG = BotConfig()
# The seeded-store fixture imports the whole question bank; bots need only an empty store and keys.
KEYS = Keyring.from_settings(make_settings())


def test_pool_has_150_valid_unique_names_weighted_to_easy_tiers():
    assert len(_NAMES) == 150 and len({n.lower() for n in _NAMES}) == 150
    assert [n for n in _NAMES if check_username(n)] == []
    tiers = Counter(b["profile"] for b in default_bots())
    assert tiers == {"BEGINNER": 50, "NORMAL": 50, "STRONG": 30, "EXPERT": 20}


def test_profiles_get_harder_along_the_ladder():
    profiles = GameConfig().bots.profiles
    order = ["BEGINNER", "NORMAL", "STRONG", "EXPERT"]
    for easier, harder in zip(order, order[1:], strict=False):
        for difficulty in ("EASY", "MEDIUM", "HARD"):
            assert profiles[easier].accuracy[difficulty] < profiles[harder].accuracy[difficulty]
            assert profiles[easier].response_mean_ms[difficulty] > profiles[harder].response_mean_ms[difficulty]
    # Never superhuman: the fastest mean stays well above the 1.3 s floor.
    assert min(profiles["EXPERT"].response_mean_ms.values()) >= 3000


def test_roster_tiers_follow_the_ladder_and_repeat_for_survival():
    assert roster_tiers(0, 3) == ["BEGINNER"] * 3
    assert roster_tiers(1.9, 3) == ["BEGINNER", "BEGINNER", "NORMAL"]
    assert roster_tiers(MAX_LEVEL + 5, 3) == ["EXPERT"] * 3
    assert roster_tiers(-2, 2) == ["BEGINNER"] * 2
    assert roster_tiers(4, 9) == ["NORMAL", "NORMAL", "STRONG"] * 3
    assert len(LADDER) == 10


def test_new_players_start_easy_and_losing_streaks_get_relief():
    assert effective_level({}, CFG) == 1.0
    # Warm-up: the first matches never exceed the warm-up cap, whatever the level.
    assert effective_level({"bot_level": 6, "matches_completed": 2}, CFG) == 1.0
    assert effective_level({"bot_level": 6, "matches_completed": 3}, CFG) == 6.0
    # Three losses in a row: one rung easier until the next win.
    assert effective_level({"bot_level": 4, "matches_completed": 9, "bot_loss_streak": 3}, CFG) == 3.0
    assert effective_level({"bot_level": 0.5, "matches_completed": 9, "bot_loss_streak": 5}, CFG) == 0.0


def test_after_match_steps_level_up_on_wins_and_down_on_losses():
    base = {"bot_level": 3.0, "bot_loss_streak": 2}
    assert after_match(base, mode="QUICK", place=1, left=False, players=4, cfg=CFG) == {
        "bot_level": 3.75, "bot_loss_streak": 0}
    assert after_match(base, mode="QUICK", place=2, left=False, players=4, cfg=CFG) == {
        "bot_level": 2.5, "bot_loss_streak": 3}
    # Leaving never eases the bots.
    assert after_match(base, mode="QUICK", place=4, left=True, players=4, cfg=CFG) == base
    # Survival: the top third holds, the rest lose half a step.
    assert after_match(base, mode="SURVIVAL", place=3, left=False, players=10, cfg=CFG)["bot_level"] == 3.0
    assert after_match(base, mode="SURVIVAL", place=7, left=False, players=10, cfg=CFG)["bot_level"] == 2.75
    assert after_match({"bot_level": 0.2}, mode="QUICK", place=3, left=False, players=4, cfg=CFG)["bot_level"] == 0
    assert after_match({"bot_level": 9}, mode="QUICK", place=1, left=False, players=4, cfg=CFG)["bot_level"] == 9


def test_break_even_win_rate_is_forty_percent():
    # A player who wins p of their matches holds level when p * win_step == (1 - p) * loss_step.
    p = CFG.loss_step / (CFG.win_step + CFG.loss_step)
    assert abs(p - 0.4) < 1e-9


def test_pick_uses_ladder_level_and_falls_back_to_nearest_tier():
    pool = BotPool(MemoryDocStore(), KEYS)
    config = GameConfig()
    easy = asyncio.run(pool.pick("m1", 3, [0.0], set(), config))
    assert [b["profile"] for b in easy] == ["BEGINNER"] * 3
    hard = asyncio.run(pool.pick("m2", 3, [9.0], set(), config))
    assert [b["profile"] for b in hard] == ["EXPERT"] * 3
    # Humans at different levels meet the average rung.
    mixed = asyncio.run(pool.pick("m3", 2, [0.0, 4.0], set(), config))
    assert [b["profile"] for b in mixed] == ["BEGINNER", "NORMAL"]
    # 30 EXPERT seats exhaust the 20 EXPERT bots; the rest come from STRONG, the nearest tier.
    many = asyncio.run(pool.pick("m4", 30, [9.0], set(), config))
    assert Counter(b["profile"] for b in many) == {"EXPERT": 20, "STRONG": 10}


def test_seed_never_takes_over_a_human_username():
    store = MemoryDocStore()
    human = {"schema_version": 1, "state": "ACTIVE", "uid": "u_human", "name": "deniz_k"}
    asyncio.run(store.set("username_registry/deniz_k", human))
    asyncio.run(seed_bots(store, KEYS, 0))
    assert asyncio.run(store.get("username_registry/deniz_k")) == human
    bot = next(b for b in store._docs.values() if b.get("username") == "deniz_k")
    assert bot["active"] is False
    assert asyncio.run(store.get("username_registry/burak_34"))["is_bot"] is True
