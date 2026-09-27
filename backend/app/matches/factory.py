"""Match factory: roster, bots, question plan, config snapshot and ranked eligibility (spec §7.5, §21.7, §26).

Everything that needs I/O happens in ``prepare`` BEFORE the roster-claim transaction; ``launch`` then writes
the canonical live root once the claim has committed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.common.clock import ms_to_datetime
from app.common.ids import new_uuid
from app.common.server_config import GameConfig, RankedConfig
from app.matches import engine
from app.matches.model import Mode
from app.matches.service import index_path
from app.matches.shards import shard_for

ROSTER_SIZE = {Mode.QUICK: 4, Mode.SURVIVAL: 10}
INDEX_TTL_MS = 7 * 86_400_000
RANKED_SOURCES = ("PUBLIC", "REMATCH")


def ranked_eligibility(mode: Mode, human_count: int, bot_count: int, ranked: RankedConfig,
                       source: str) -> dict[str, Any]:
    """Ranked only with enough human opponents (spec §7.5); config can only make it stricter."""
    minimum = ranked.quick_min_total_humans if mode == Mode.QUICK else ranked.survival_min_total_humans
    if source not in RANKED_SOURCES:
        # Friend challenges never move MMR (prevents arranged rating farming between friends).
        eligible, reason = False, "private_match"
    elif human_count < minimum:
        eligible, reason = False, "insufficient_human_opponents"
    else:
        eligible, reason = True, "ok"
    return {"eligible": eligible, "reason": reason, "human_slots": human_count, "bot_slots": bot_count,
            "min_total_humans": minimum}


@dataclass
class HumanSeat:
    uid: str
    username: str
    avatar_id: str
    frame_id: str
    mmr: int
    ticket_id: str | None = None


@dataclass
class PreparedMatch:
    match_id: str
    shard_id: str
    mode: Mode
    language: str
    region: str
    source: str
    humans: list[HumanSeat]
    roster: list[dict[str, Any]]
    bot_profiles: dict[str, dict[str, Any]]
    plan: dict[str, Any]
    config_snapshot: dict[str, Any]
    ranked: dict[str, Any]
    reaction_ids: list[str]
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def human_uids(self) -> list[str]:
        return [h.uid for h in self.humans]


class MatchFactory:
    def __init__(self, container) -> None:
        self._c = container

    async def prepare(self, *, mode: Mode, language: str, humans: list[HumanSeat], source: str = "PUBLIC",
                      fill_bots: bool = True, config: GameConfig | None = None,
                      category_id: str | None = None) -> PreparedMatch:
        c = self._c
        config = config or await c.config.get()
        match_id = new_uuid()
        shard_id = shard_for(c.keys, match_id, c.settings.shard_ids)
        await c.shard_admission.check(shard_id, config.matchmaking.max_active_rooms_per_shard)
        bot_count = max(0, ROSTER_SIZE[mode] - len(humans)) if fill_bots else 0
        avg_mmr = sum(h.mmr for h in humans) / max(1, len(humans))
        bots = await c.bots.pick(match_id, bot_count, avg_mmr, {h.username.lower() for h in humans}, config)
        uids = [h.uid for h in humans]
        if mode == Mode.QUICK:
            plan = await c.question_plans.quick_plan(language, uids, seed=match_id, category_id=category_id)
        else:
            plan = {"pools": await c.question_plans.survival_plan(language, uids, seed=match_id,
                                                                  category_id=category_id)}
        if category_id:
            plan["category_id"] = category_id
        roster: list[dict[str, Any]] = [
            {"pid": c.profiles.public_id(h.uid), "kind": "HUMAN", "uid": h.uid, "username": h.username,
             "avatar_id": h.avatar_id, "frame_id": h.frame_id, "pre_match_mmr": h.mmr} for h in humans]
        bot_profiles: dict[str, dict[str, Any]] = {}
        for bot in bots:
            pid = c.bots.public_id(bot["bot_id"])
            roster.append({"pid": pid, "kind": "BOT", "bot_id": bot["bot_id"], "username": bot["username"],
                           "avatar_id": bot["avatar_id"], "frame_id": "frame_none", "pre_match_mmr": bot["mmr"]})
            bot_profiles[pid] = bot["profile_config"]
        reactions = [r["id"] for r in await c.catalog.reactions()]
        return PreparedMatch(
            match_id=match_id, shard_id=shard_id, mode=mode, language=language, region=c.settings.region,
            source=source, humans=humans, roster=roster, bot_profiles=bot_profiles, plan=plan,
            config_snapshot={**config.match_snapshot(mode.value),
                             "bots": {"reaction_probability": config.bots.reaction_probability},
                             "retention": config.retention.model_dump()},
            ranked=ranked_eligibility(mode, len(humans), len(bots), config.ranked, source),
            reaction_ids=reactions,
            extra={"category_id": category_id} if category_id else {},
        )

    def index_doc(self, prepared: PreparedMatch, now_ms: int) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "match_id": prepared.match_id,
            "mode": prepared.mode.value,
            "language": prepared.language,
            "region": prepared.region,
            "source": prepared.source,
            "rtdb_shard_id": prepared.shard_id,
            "client_rtdb_url_selector": prepared.shard_id,
            "state": "PREPARING",
            "participant_uids": prepared.human_uids,
            "spectator_uids": [],
            "ranked_eligible": prepared.ranked["eligible"],
            "created_at_ms": now_ms,
            "expires_at": ms_to_datetime(now_ms + INDEX_TTL_MS),
            **prepared.extra,
        }

    def write_index_in_txn(self, txn, prepared: PreparedMatch, now_ms: int) -> None:
        txn.create(index_path(prepared.match_id), self.index_doc(prepared, now_ms))
        self._c.shard_admission.room_opened_in_txn(txn, prepared.shard_id, now_ms)

    async def launch(self, prepared: PreparedMatch) -> None:
        """Create the canonical root after the claim committed. A failure cancels the unstarted match."""
        c = self._c
        now = c.clock.now_ms()
        try:
            state, result = engine.create_match_state(
                keys=c.keys, match_id=prepared.match_id, shard_id=prepared.shard_id, mode=prepared.mode,
                language=prepared.language, region=prepared.region, roster=prepared.roster, plan=prepared.plan,
                config_snapshot=prepared.config_snapshot, bot_profiles=prepared.bot_profiles,
                reaction_ids=prepared.reaction_ids, ranked=prepared.ranked, source=prepared.source, now_ms=now)
            await c.matches.create_live(prepared.match_id, prepared.shard_id, state, result)
            await c.store.update(index_path(prepared.match_id), {"state": "LIVE", "started_at_ms": now})
        except Exception:
            await c.settlement.abort_unstarted(prepared.match_id, "LIVE_CREATE_FAILED")
            raise
