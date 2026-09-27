"""Weekly cohort leagues (playtest 2026-09-27).

Every UTC ISO week a player who plays a ranked match joins a group of ``group_size`` seats in their tier. Seats
not taken by humans are held by league bots whose weekly XP grows deterministically over the week, so a group is
always full and standings move even with few players. At the next week the player's final rank in last week's
group decides promotion (top ``promote``), relegation (bottom ``demote``, never below Bronze) or staying.

Groups are never numbered to players: a Bronze player simply sees "Bronze league" with their 100 rivals.

Documents:
- ``league_groups/{week}_{tier}_{index}``: seats (human uids + the bot roster), open flag.
- ``league_meta/{week}_{tier}``: index of the group currently filling.
- ``league_meta/{week}``: number of humans who joined a group that week (drives the ranked bootstrap).
- ``users/{uid}.league_tier`` / ``league_state`` ({week_id, group_id, last_result}).
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime
from typing import Any

from app.catalog.data import AVATARS
from app.common.clock import iso_week_id
from app.common.ids import sha256_hex
from app.common.server_config import LeagueConfig
from app.ranking.leagues import START_TIER, League, promoted, relegated, tier_index, tier_of

WEEK_MS = 7 * 86_400_000
BOT_POOL_PER_TIER = 140

_FIRST = [
    "ada", "alp", "arda", "aria", "ayla", "baran", "bora", "cem", "cleo", "dara", "defne", "deniz", "duru", "ece",
    "efe", "elif", "emir", "eren", "ezra", "finn", "gaia", "iris", "jade", "kaan", "kiara", "lara", "leon", "lia",
    "luca", "mert", "mila", "nehir", "nico", "nora", "ozan", "pia", "remy", "ruzgar", "sara", "sena", "taylan",
    "tuna", "umut", "vega", "yaren", "yusuf", "zeyn", "zoe", "berk", "ceren", "doruk", "ekin", "hazal", "ilgaz",
]
_SUFFIX = ["", "_q", "_x", "_07", "_42", "_99", "_tr", "_io", "_z", "_k", "_m", "_2k", "_fx", "_pro", "_one"]


def week_bounds(week_id: str) -> tuple[int, int]:
    year, week = week_id.split("-W")
    start = datetime.fromisocalendar(int(year), int(week), 1).replace(tzinfo=UTC)
    start_ms = int(start.timestamp() * 1000)
    return start_ms, start_ms + WEEK_MS


def previous_week(week_id: str) -> str:
    start, _ = week_bounds(week_id)
    return iso_week_id(start - 1)


def group_path(group_id: str) -> str:
    return f"league_groups/{group_id}"


def _pointer_path(week_id: str, tier: str) -> str:
    return f"league_meta/{week_id}_{tier}"


def _week_meta_path(week_id: str) -> str:
    return f"league_meta/{week_id}"


def bot_identities(tier: str) -> list[dict[str, Any]]:
    """Deterministic identity pool for league bots of one tier (same shape as players on every screen)."""
    rng = random.Random(f"league-bots:{tier}")
    names: list[str] = []
    seen: set[str] = set()
    while len(names) < BOT_POOL_PER_TIER:
        name = f"{rng.choice(_FIRST)}{rng.choice(_SUFFIX)}"
        if name not in seen:
            seen.add(name)
            names.append(name)
    return [{"bot_id": f"lbot_{tier.lower()}_{i:03d}", "username": name,
             "avatar_id": AVATARS[rng.randrange(len(AVATARS))]["id"]} for i, name in enumerate(names)]


def _bot_seats(group_id: str, tier: str, cfg: LeagueConfig) -> list[dict[str, Any]]:
    """Bots for a new group with their weekly XP curve: target XP (log-uniform, higher tiers play more) and the
    fraction of the week after which they start playing."""
    rng = random.Random(f"league-group:{group_id}")
    pool = bot_identities(tier)
    rng.shuffle(pool)
    factor = cfg.bot_xp_tier_factor ** tier_index(tier)
    low, high = math.log(cfg.bot_xp_min * factor), math.log(cfg.bot_xp_max * factor)
    seats = []
    for bot in pool[:cfg.group_size]:
        seats.append({**bot, "target_xp": int(math.exp(rng.uniform(low, high))),
                      "start": round(rng.uniform(0.0, 0.5), 3)})
    return seats


def bot_weekly_xp(seat: dict[str, Any], week_id: str, now_ms: int) -> int:
    start_ms, end_ms = week_bounds(week_id)
    elapsed = min(1.0, max(0.0, (now_ms - start_ms) / (end_ms - start_ms)))
    begin = float(seat.get("start", 0.0))
    if elapsed <= begin:
        return 0
    return int(seat["target_xp"] * min(1.0, (elapsed - begin) / (1.0 - begin)))


class LeagueService:
    def __init__(self, container) -> None:
        self._c = container

    async def _cfg(self) -> LeagueConfig:
        return (await self._c.config.get()).leagues

    # ------------------------------------------------------------------------------------------ bootstrap
    async def active_humans(self, now_ms: int) -> int:
        week = iso_week_id(now_ms)
        docs = await self._c.store.get_many([_week_meta_path(week), _week_meta_path(previous_week(week))])
        return max(int((d or {}).get("humans", 0)) for d in docs)

    async def bootstrap_active(self, now_ms: int) -> bool:
        cfg = await self._cfg()
        return await self.active_humans(now_ms) < cfg.bootstrap_active_humans

    # ------------------------------------------------------------------------------------------ membership
    async def roll_over(self, uid: str, now_ms: int) -> dict[str, Any]:
        """Apply last week's promotion/relegation once the week is over; returns the user's league fields."""
        c = self._c
        user = await c.store.get(f"users/{uid}") or {}
        state = dict(user.get("league_state") or {})
        tier = tier_of(user)
        week = iso_week_id(now_ms)
        if not state.get("group_id") or state.get("week_id") == week:
            return {"league_tier": tier.value, "league_state": state}
        cfg = await self._cfg()
        old_week = state["week_id"]
        rows = await self.standings(state["group_id"], week_bounds(old_week)[1] - 1)
        rank = next((r["rank"] for r in rows if r.get("uid") == uid), len(rows))
        size = len(rows)
        if rank <= cfg.promote and tier != League.LEGEND:
            new_tier, outcome = promoted(tier), "PROMOTED"
        elif rank > size - cfg.demote and tier != League.BRONZE:
            new_tier, outcome = relegated(tier), "RELEGATED"
        else:
            new_tier, outcome = tier, "STAYED"
        state = {"week_id": None, "group_id": None,
                 "last_result": {"week_id": old_week, "rank": rank, "from": tier.value, "to": new_tier.value,
                                 "outcome": outcome}}
        await c.store.update(f"users/{uid}", {"league_tier": new_tier.value, "league_state": state})
        return {"league_tier": new_tier.value, "league_state": state}

    async def ensure_group(self, uid: str, now_ms: int) -> str:
        """The player's group for this week, joining (after any rollover) on their first ranked match."""
        fields = await self.roll_over(uid, now_ms)
        state = fields["league_state"]
        week = iso_week_id(now_ms)
        if state.get("week_id") == week and state.get("group_id"):
            return state["group_id"]
        tier = fields["league_tier"]
        group_id = await self._join(uid, week, tier, now_ms)
        await self._c.store.update(f"users/{uid}", {"league_state": {**state, "week_id": week,
                                                                     "group_id": group_id}})
        return group_id

    async def _join(self, uid: str, week: str, tier: str, now_ms: int) -> str:
        c = self._c
        cfg = await self._cfg()

        def txn_fn(txn) -> str:
            pointer = txn.get(_pointer_path(week, tier)) or {"index": 1}
            index = int(pointer["index"])
            group_id = f"{week}_{tier}_{index:04d}"
            group = txn.get(group_path(group_id))
            if group and uid in group.get("human_uids", []):
                return group_id
            if group and len(group.get("human_uids", [])) >= cfg.group_size:
                index += 1
                group_id = f"{week}_{tier}_{index:04d}"
                group = txn.get(group_path(group_id))
            meta = txn.get(_week_meta_path(week)) or {"humans": 0}
            fresh_bots: list[dict[str, Any]] = []
            if group is None:
                seats = _bot_seats(group_id, tier, cfg)
                registry = txn.get_many([f"username_registry/{s['username']}" for s in seats])
                for seat, reg in zip(seats, registry, strict=True):
                    # A name a human already owns is never used by a bot.
                    if reg is None or reg.get("uid") == f"bot:{seat['bot_id']}":
                        fresh_bots.append({**seat, "registered": reg is not None})
                group = {"schema_version": 1, "group_id": group_id, "week_id": week, "tier": tier, "index": index,
                         "human_uids": [], "bots": [{k: v for k, v in b.items() if k != "registered"}
                                                    for b in fresh_bots],
                         "created_at_ms": now_ms}
            humans = [*group.get("human_uids", []), uid]
            group = {**group, "human_uids": humans, "open": len(humans) < cfg.group_size, "updated_at_ms": now_ms}
            txn.set(group_path(group_id), group)
            txn.set(_pointer_path(week, tier), {"index": index, "updated_at_ms": now_ms})
            txn.set(_week_meta_path(week), {"week_id": week, "humans": int(meta.get("humans", 0)) + 1,
                                            "updated_at_ms": now_ms})
            for bot in fresh_bots:
                self._write_bot_identity(txn, bot, tier, now_ms)
            return group_id

        return await c.store.run_transaction(txn_fn)

    def _write_bot_identity(self, txn, bot: dict[str, Any], tier: str, now_ms: int) -> None:
        public_id = self.bot_public_id(bot["bot_id"])
        if not bot.get("registered"):
            txn.set(f"username_registry/{bot['username']}", {
                "schema_version": 1, "state": "ACTIVE", "uid": f"bot:{bot['bot_id']}", "is_bot": True,
                "name": bot["username"], "updated_at_ms": now_ms})
        rng = random.Random(bot["bot_id"])
        txn.set(f"public_profiles/{public_id}", {
            "schema_version": 1, "public_id": public_id, "username_display": bot["username"],
            "avatar_id": bot["avatar_id"], "frame_id": "frame_none", "featured_badge_ids": [], "league": tier,
            "level": 3 + tier_index(tier) * 4 + rng.randint(0, 12),
            "quick_best_ranked_win_streak": rng.randint(0, 6), "survival_ranked_crowns_lifetime": rng.randint(0, 3),
            "quick_ranked_wins_lifetime": rng.randint(3, 60)})
        txn.set(f"public_ids/{public_id}", {"uid": f"bot:{bot['bot_id']}", "is_bot": True})

    def bot_public_id(self, bot_id: str) -> str:
        # Same shape as human public IDs so clients cannot tell them apart (D3).
        return "p" + self._c.keys.username_hash.hexdigest(f"public-id:bot:{bot_id}")[:19]

    # ------------------------------------------------------------------------------------------ standings
    async def standings(self, group_id: str, now_ms: int) -> list[dict[str, Any]]:
        """Full group table: humans by their weekly XP, remaining seats by bots, ranked by XP."""
        c = self._c
        cfg = await self._cfg()
        group = await c.store.get(group_path(group_id))
        if not group:
            return []
        week = group["week_id"]
        from app.progression.service import weekly_path

        humans = list(group.get("human_uids") or [])
        weekly = await c.store.get_many([weekly_path(week, uid) for uid in humans]) if humans else []
        users = await c.store.get_many([f"users/{uid}" for uid in humans]) if humans else []
        rows: list[dict[str, Any]] = []
        for uid, stats, user in zip(humans, weekly, users, strict=True):
            user = user or {}
            rows.append({"uid": uid, "public_id": user.get("public_id"),
                         "username": user.get("username_display"), "avatar_id": user.get("avatar_id"),
                         "frame_id": user.get("frame_id", "frame_none"),
                         "weekly_xp": int((stats or {}).get("ranked_weekly_xp", 0)),
                         "tie": sha256_hex(f"league:{uid}")[:12]})
        for seat in (group.get("bots") or [])[:max(0, cfg.group_size - len(humans))]:
            rows.append({"uid": None, "public_id": self.bot_public_id(seat["bot_id"]), "username": seat["username"],
                         "avatar_id": seat["avatar_id"], "frame_id": "frame_none",
                         "weekly_xp": bot_weekly_xp(seat, week, now_ms),
                         "tie": sha256_hex(f"league:{seat['bot_id']}")[:12]})
        rows.sort(key=lambda r: (-r["weekly_xp"], r["tie"]))
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        return rows

    async def view(self, uid: str, now_ms: int) -> dict[str, Any]:
        """Client payload for the league screen. Bots and humans look the same (D3); no group number is shown."""
        cfg = await self._cfg()
        fields = await self.roll_over(uid, now_ms)
        tier = League(fields["league_tier"])
        state = fields["league_state"]
        week = iso_week_id(now_ms)
        joined = state.get("week_id") == week and bool(state.get("group_id"))
        rows = await self.standings(state["group_id"], now_ms) if joined else []
        size = len(rows) or cfg.group_size
        promote = cfg.promote if tier != League.LEGEND else 0
        demote = cfg.demote if tier != League.BRONZE else 0
        me = next((r for r in rows if r["uid"] == uid), None)
        return {
            "schema_version": 1,
            "league": tier.value,
            "leagues": [t.value for t in League],
            "week_id": week,
            "week_ends_at_ms": week_bounds(week)[1],
            "joined": joined,
            "group_size": size,
            "promote_count": promote,
            "demote_count": demote,
            "rank": me["rank"] if me else None,
            "ranked_weekly_xp": me["weekly_xp"] if me else 0,
            "last_result": state.get("last_result"),
            "standings": [{"rank": r["rank"], "public_id": r["public_id"], "username": r["username"],
                           "avatar_id": r["avatar_id"], "frame_id": r["frame_id"], "weekly_xp": r["weekly_xp"],
                           "me": r["uid"] == uid,
                           "zone": ("PROMOTE" if r["rank"] <= promote
                                    else "DEMOTE" if r["rank"] > size - demote else None)} for r in rows],
        }


__all__ = ["LeagueService", "START_TIER", "bot_weekly_xp", "bot_identities", "week_bounds"]
