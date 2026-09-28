"""Public matchmaking: durable tickets, runtime locks and atomic roster claims (spec §21).

Matchmaking state never lives only in Cloud Run memory. A roster becomes a match only through one DocStore
transaction that re-reads every ticket and runtime lock, so two instances can never double-match a player.
"""

from __future__ import annotations

import logging
from typing import Any

from app.accounts.runtime import RuntimeState, current, pointer, require_idle, runtime_path, transition
from app.bots.difficulty import effective_level
from app.common.clock import ms_to_datetime
from app.common.errors import ApiError, ErrorCode
from app.common.ids import new_uuid
from app.common.server_config import GameConfig
from app.common.store.docstore import Query
from app.matches.factory import ROSTER_SIZE, HumanSeat, PreparedMatch
from app.matches.model import Mode
from app.moderation.safety import SafetyService
from app.moderation.sanctions import ensure_can_play
from app.questions.selector import InsufficientInventory

log = logging.getLogger("oltivra.matchmaking")

LATENCY_BANDS = ("0_60", "61_120", "121_200", "201_plus")
TICKET_RETENTION_MS = 7 * 86_400_000
MAX_CLAIM_ATTEMPTS = 3


def latency_band(median_rtt_ms: int, bands_ms: list[int]) -> str:
    """Client median RTT only groups players; it never decides a winner (spec §21.2)."""
    for label, limit in zip(LATENCY_BANDS, bands_ms, strict=False):
        if median_rtt_ms <= limit:
            return label
    return LATENCY_BANDS[-1]


def ticket_path(ticket_id: str) -> str:
    return f"matchmaking_tickets/{ticket_id}"


class MatchmakingService:
    def __init__(self, container) -> None:
        self._c = container

    # ------------------------------------------------------------------------------------------ join / leave
    async def join(self, uid: str, user: dict[str, Any], mode: Mode, median_rtt_ms: int,
                   request_id: str, category_id: str | None = None) -> dict[str, Any]:
        c = self._c
        config = await c.config.get()
        if not config.features.new_matches_enabled:
            raise ApiError(ErrorCode.CAPACITY_UNAVAILABLE, retry_after_s=30, detail={"reason": "new_matches_paused"})
        if mode == Mode.SURVIVAL and not config.features.survival_enabled:
            raise ApiError(ErrorCode.FEATURE_DISABLED, detail={"feature": "survival"})
        language = user.get("question_language", "en")
        if language not in config.features.competitive_languages:
            raise ApiError(ErrorCode.FEATURE_DISABLED, detail={"feature": "question_language", "language": language})
        if category_id is not None and category_id not in config.features.category_queues_for(
                language, c.settings.region):
            raise ApiError(ErrorCode.FEATURE_DISABLED, detail={"feature": "category_queue", "category_id": category_id})
        now = c.clock.now_ms()
        ensure_can_play(user, now)
        fill_ms = config.quick.bot_fill_ms if mode == Mode.QUICK else config.survival.bot_fill_ms
        ticket = {
            "schema_version": 1,
            "ticket_id": new_uuid(),
            "uid": uid,
            "mode": mode.value,
            "language": language,
            "region": c.settings.region,
            "latency_band": latency_band(median_rtt_ms, config.matchmaking.ping_bands_ms),
            # None = Mixed. Category tickets only ever match the same category (never widened into Mixed).
            "category_id": category_id,
            "median_rtt_ms": median_rtt_ms,
            "mmr_snapshot": int(user.get("mmr", config.ranked.start_mmr)),
            "bot_level_snapshot": effective_level(user, config.bots),
            "username": user["username_display"],
            "avatar_id": user["avatar_id"],
            "frame_id": user.get("frame_id", "frame_none"),
            "created_at_ms": now,
            "human_fill_at_ms": now + fill_ms,
            "expires_at_ms": now + config.matchmaking.ticket_ttl_ms,
            "expires_at": ms_to_datetime(now + config.matchmaking.ticket_ttl_ms),
            "retain_until": ms_to_datetime(now + TICKET_RETENTION_MS),
            "state": "QUEUED",
            "claim_id": None,
            "match_id": None,
            "request_id": request_id,
        }

        def txn_fn(txn) -> dict[str, Any]:
            runtime = current(txn.get(runtime_path(uid)), uid, now)
            if runtime["state"] == RuntimeState.QUEUED and runtime.get("active_ticket_id"):
                existing = txn.get(ticket_path(runtime["active_ticket_id"]))
                if existing and existing.get("state") == "QUEUED" and existing.get("mode") == mode.value \
                        and existing.get("category_id") == category_id:
                    return existing  # duplicate join returns the active ticket
            require_idle(runtime)
            txn.create(ticket_path(ticket["ticket_id"]), ticket)
            txn.set(runtime_path(uid), transition(runtime, RuntimeState.QUEUED, now,
                                                  active_ticket_id=ticket["ticket_id"]))
            return ticket

        active = await c.store.run_transaction(txn_fn)
        return await self._progress(uid, active, config)

    async def leave(self, uid: str, mode: Mode) -> dict[str, Any]:
        """QUEUED -> CANCELLED only; a matched player gets the match pointer instead (spec §21.3)."""
        now = self._c.clock.now_ms()

        def txn_fn(txn) -> dict[str, Any]:
            runtime = current(txn.get(runtime_path(uid)), uid, now)
            ticket = txn.get(ticket_path(runtime["active_ticket_id"])) if runtime.get("active_ticket_id") else None
            if runtime["state"] != RuntimeState.QUEUED:
                return {"state": "IDLE" if runtime["state"] == RuntimeState.IDLE else "MATCHED",
                        "runtime": pointer(runtime)}
            if ticket and ticket.get("mode") != mode.value:
                raise ApiError(ErrorCode.QUEUE_TICKET_NOT_ACTIVE, detail={"queued_mode": ticket.get("mode")})
            if ticket and ticket.get("state") == "QUEUED":
                txn.update(ticket_path(ticket["ticket_id"]), {"state": "CANCELLED", "updated_at_ms": now})
            txn.set(runtime_path(uid), transition(runtime, RuntimeState.IDLE, now))
            return {"state": "CANCELLED", "ticket_id": ticket["ticket_id"] if ticket else None}

        result = await self._c.store.run_transaction(txn_fn)
        if result["state"] == "MATCHED":
            return await self.status(uid)
        return {"schema_version": 1, **result}

    async def status(self, uid: str) -> dict[str, Any]:
        """Polled at ``human_fill_at_ms``; this request is the normal trigger for bot fill (spec §21.3)."""
        c = self._c
        now = c.clock.now_ms()
        runtime = current(await c.store.get(runtime_path(uid)), uid, now)
        state = RuntimeState(runtime["state"])
        if state == RuntimeState.QUEUED and runtime.get("active_ticket_id"):
            ticket = await c.store.get(ticket_path(runtime["active_ticket_id"]))
            if ticket:
                return await self._progress(uid, ticket, await c.config.get())
        if state == RuntimeState.MATCH_ACTIVE:
            return await self._matched_view(runtime["active_match_id"])
        if state == RuntimeState.SETTLEMENT_PENDING:
            return {"schema_version": 1, "state": "SETTLEMENT_PENDING",
                    "match": {"match_id": runtime.get("pending_settlement_match_id")}, "server_time_ms": now}
        return {"schema_version": 1, "state": state.value if state != RuntimeState.QUEUED else "IDLE",
                "server_time_ms": now}

    # ------------------------------------------------------------------------------------------ internals
    async def _matched_view(self, match_id: str) -> dict[str, Any]:
        idx = await self._c.store.get(f"match_index/{match_id}") or {}
        shard = idx.get("rtdb_shard_id")
        return {"schema_version": 1, "state": "MATCHED", "server_time_ms": self._c.clock.now_ms(),
                "match": {"match_id": match_id, "mode": idx.get("mode"), "rtdb_shard_id": shard,
                          "client_rtdb_url_selector": idx.get("client_rtdb_url_selector", shard),
                          "rtdb_url": self._c.settings.shard_url(shard) if shard else None}}

    def _queued_view(self, ticket: dict[str, Any], now: int, retry_after_ms: int | None = None) -> dict[str, Any]:
        fill_at = ticket["human_fill_at_ms"]
        next_poll = fill_at if now < fill_at else now + (retry_after_ms or 1000)
        return {"schema_version": 1, "state": "QUEUED", "ticket_id": ticket["ticket_id"], "mode": ticket["mode"],
                "latency_band": ticket["latency_band"], "category_id": ticket.get("category_id"),
                "human_fill_at_ms": fill_at,
                "expires_at_ms": ticket["expires_at_ms"], "next_poll_at_ms": min(next_poll, ticket["expires_at_ms"]),
                "server_time_ms": now}

    async def _progress(self, uid: str, ticket: dict[str, Any], config: GameConfig) -> dict[str, Any]:
        now = self._c.clock.now_ms()
        if ticket.get("state") == "MATCHED" and ticket.get("match_id"):
            return await self._matched_view(ticket["match_id"])
        if ticket.get("state") != "QUEUED":
            return {"schema_version": 1, "state": ticket.get("state"), "ticket_id": ticket["ticket_id"],
                    "server_time_ms": now}
        if now >= ticket["expires_at_ms"]:
            await self.expire_ticket(ticket["ticket_id"])
            return {"schema_version": 1, "state": "EXPIRED", "ticket_id": ticket["ticket_id"], "server_time_ms": now}
        try:
            match_id = await self.try_form(ticket, allow_bots=now >= ticket["human_fill_at_ms"], config=config)
        except ApiError as exc:
            if exc.code != ErrorCode.CAPACITY_UNAVAILABLE:
                raise
            # Never hide a capacity failure behind an endless queue: the ticket still expires on schedule.
            return {**self._queued_view(ticket, now, (exc.retry_after_s or 5) * 1000), "capacity_limited": True}
        if match_id:
            return await self._matched_view(match_id)
        return self._queued_view(ticket, now)

    async def expire_ticket(self, ticket_id: str) -> None:
        now = self._c.clock.now_ms()

        def txn_fn(txn) -> None:
            ticket = txn.get(ticket_path(ticket_id))
            if not ticket or ticket.get("state") != "QUEUED" or ticket["expires_at_ms"] > now:
                return
            runtime = current(txn.get(runtime_path(ticket["uid"])), ticket["uid"], now)
            txn.update(ticket_path(ticket_id), {"state": "EXPIRED", "updated_at_ms": now})
            if runtime["state"] == RuntimeState.QUEUED and runtime.get("active_ticket_id") == ticket_id:
                txn.set(runtime_path(ticket["uid"]), transition(runtime, RuntimeState.IDLE, now))

        await self._c.store.run_transaction(txn_fn)

    async def sweep_expired(self, limit: int = 500) -> int:
        """Low-frequency maintenance sweep (Cloud Scheduler, spec §20.6)."""
        now = self._c.clock.now_ms()
        rows = await self._c.store.query(Query("matchmaking_tickets").filter("state", "==", "QUEUED")
                                         .filter("expires_at_ms", "<=", now).take(limit))
        for row in rows:
            await self.expire_ticket(row.data["ticket_id"])
        return len(rows)

    async def _candidates(self, ticket: dict[str, Any], config: GameConfig) -> list[dict[str, Any]]:
        query = (Query("matchmaking_tickets").filter("state", "==", "QUEUED").filter("mode", "==", ticket["mode"])
                 .filter("language", "==", ticket["language"]).filter("region", "==", ticket["region"])
                 .filter("latency_band", "==", ticket["latency_band"])
                 .filter("category_id", "==", ticket.get("category_id")).order("created_at_ms")
                 .take(config.matchmaking.candidate_scan_limit))
        now = self._c.clock.now_ms()
        return [r.data for r in await self._c.store.query(query)
                if r.data["ticket_id"] != ticket["ticket_id"] and r.data["expires_at_ms"] > now]

    async def select_roster(self, ticket: dict[str, Any], config: GameConfig,
                            exclude_uids: set[str]) -> list[dict[str, Any]]:
        """Formation steps 1–5 (spec §21.7): same partition, never widen region/latency, widen MMR only."""
        now = self._c.clock.now_ms()
        target = ROSTER_SIZE[Mode(ticket["mode"])]
        candidates = [t for t in await self._candidates(ticket, config) if t["uid"] not in exclude_uids]
        oldest = min([ticket["created_at_ms"], *(t["created_at_ms"] for t in candidates)])
        widened = now - oldest >= config.matchmaking.widen_after_ms
        mmr_range = config.matchmaking.widened_mmr_range if widened else config.matchmaking.initial_mmr_range
        candidates.sort(key=lambda t: (t["created_at_ms"], abs(t["mmr_snapshot"] - ticket["mmr_snapshot"])))
        safety: SafetyService = self._c.safety
        blocked = {ticket["uid"]: await safety.block_set(ticket["uid"])}
        roster = [ticket]
        for cand in candidates:
            if len(roster) >= target:
                break
            if abs(cand["mmr_snapshot"] - ticket["mmr_snapshot"]) > mmr_range:
                continue
            if any(cand["uid"] == t["uid"] for t in roster):
                continue
            if any(cand["uid"] in blocked[t["uid"]] for t in roster):
                continue
            blocked[cand["uid"]] = await safety.block_set(cand["uid"])
            roster.append(cand)
        return roster

    async def try_form(self, ticket: dict[str, Any], *, allow_bots: bool, config: GameConfig) -> str | None:
        """Steps 6–8: claim a full human roster, or at the fill deadline claim available humans + bots."""
        c = self._c
        target = ROSTER_SIZE[Mode(ticket["mode"])]
        excluded: set[str] = set()
        for _ in range(MAX_CLAIM_ATTEMPTS):
            roster = await self.select_roster(ticket, config, excluded)
            if len(roster) < target and not allow_bots:
                return None
            seats = [HumanSeat(uid=t["uid"], username=t["username"], avatar_id=t["avatar_id"],
                               frame_id=t.get("frame_id", "frame_none"), mmr=t["mmr_snapshot"],
                               ticket_id=t["ticket_id"], bot_level=t.get("bot_level_snapshot")) for t in roster]
            try:
                prepared = await c.match_factory.prepare(mode=Mode(ticket["mode"]), language=ticket["language"],
                                                         humans=seats, config=config,
                                                         category_id=ticket.get("category_id"))
            except InsufficientInventory as exc:
                raise ApiError(ErrorCode.CAPACITY_UNAVAILABLE, retry_after_s=10,
                               detail={"reason": "question_inventory"}) from exc
            failed = await self.claim(prepared)
            if not failed:
                await c.match_factory.launch(prepared)
                return prepared.match_id
            if ticket["uid"] in failed:
                return None  # the caller itself was matched/cancelled concurrently; status re-reads runtime
            excluded |= failed
        return None

    async def claim(self, prepared: PreparedMatch) -> set[str]:
        """The roster-claim transaction (spec §21.7). Returns UIDs that failed validation (empty = success)."""
        c = self._c
        now = c.clock.now_ms()
        seats = prepared.humans
        claim_id = new_uuid()

        def txn_fn(txn) -> set[str]:
            paths = [ticket_path(s.ticket_id) for s in seats] + [runtime_path(s.uid) for s in seats]
            docs = txn.get_many(paths)
            tickets, runtimes = docs[:len(seats)], docs[len(seats):]
            failed: set[str] = set()
            for seat, ticket, runtime_doc in zip(seats, tickets, runtimes, strict=True):
                runtime = current(runtime_doc, seat.uid, now)
                if (not ticket or ticket.get("state") != "QUEUED" or ticket["expires_at_ms"] <= now
                        or runtime["state"] != RuntimeState.QUEUED
                        or runtime.get("active_ticket_id") != seat.ticket_id):
                    failed.add(seat.uid)
            # Blocks are re-checked inside the claim (a block created while queued must not match the pair).
            for i, a in enumerate(seats):
                for b in seats[i + 1:]:
                    if SafetyService.blocked_either_way_in_txn(txn, a.uid, b.uid):
                        failed.add(b.uid)
            if failed:
                return failed
            for seat, runtime_doc in zip(seats, runtimes, strict=True):
                runtime = current(runtime_doc, seat.uid, now)
                txn.update(ticket_path(seat.ticket_id), {"state": "MATCHED", "claim_id": claim_id,
                                                         "match_id": prepared.match_id, "updated_at_ms": now})
                txn.set(runtime_path(seat.uid), transition(
                    runtime, RuntimeState.MATCH_ACTIVE, now, active_ticket_id=None,
                    active_match_id=prepared.match_id, active_shard_id=prepared.shard_id))
            c.match_factory.write_index_in_txn(txn, prepared, now)
            return set()

        return await c.store.run_transaction(txn_fn)
