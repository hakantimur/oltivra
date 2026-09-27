"""Live match service: canonical RTDB root transactions and post-commit effects (spec §17, §19, §20).

Every transition runs the pure engine inside ONE transaction at ``/matches/{match_id}`` so authoritative,
public and player-private branches change atomically. Effects (task scheduling, media signing, settlement)
run only after the transaction commits; if any of them fail, the sync fallback and recovery tasks rediscover
due work from canonical state.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.accounts.runtime import RuntimeState, current, runtime_path, transition
from app.common.errors import ApiError, ErrorCode
from app.common.store.livestore import NO_WRITE
from app.common.tasks import TaskKind, TaskRequest
from app.matches import engine
from app.matches.model import TERMINAL_STATES, Effect, MatchState, StepResult

log = logging.getLogger("oltivra.matches")

_TASK_KINDS = {k.value for k in TaskKind}


def root_path(match_id: str) -> str:
    return f"matches/{match_id}"


def index_path(match_id: str) -> str:
    return f"match_index/{match_id}"


class MatchService:
    def __init__(self, container) -> None:
        self._c = container

    # ------------------------------------------------------------------------------------------ plumbing
    @property
    def _keys(self):
        return self._c.keys

    async def index(self, match_id: str) -> dict[str, Any]:
        doc = await self._c.store.get(index_path(match_id))
        if not doc:
            raise ApiError(ErrorCode.MATCH_NOT_FOUND)
        return doc

    def _root_value(self, state: dict[str, Any], presence: Any) -> dict[str, Any]:
        root = engine.project(state, self._keys)
        if presence:
            root["presence"] = presence
        return root

    async def create_live(self, match_id: str, shard_id: str, state: dict[str, Any], result: StepResult) -> bool:
        """Write the canonical root exactly once (a retried creation is a no-op)."""

        def fn(current_root: Any):
            if current_root and current_root.get("authoritative"):
                return NO_WRITE, False
            return self._root_value(state, None), True

        created = await self._c.live.transaction(shard_id, root_path(match_id), fn)
        if created:
            await self.run_effects(match_id, shard_id, state, result.effects)
        return created

    async def mutate(self, match_id: str, shard_id: str,
                     step: Callable[[dict[str, Any]], StepResult]) -> tuple[StepResult, dict[str, Any]]:
        """Run one pure engine step inside the canonical root transaction; execute effects after commit."""

        def fn(current_root: Any):
            if not current_root or not current_root.get("authoritative"):
                return NO_WRITE, (None, None)
            state = current_root["authoritative"]
            result = step(state)
            if not result.changed:
                return NO_WRITE, (result, state)
            return self._root_value(state, current_root.get("presence")), (result, state)

        result, state = await self._c.live.transaction(shard_id, root_path(match_id), fn)
        if result is None:
            raise ApiError(ErrorCode.MATCH_NOT_FOUND, detail={"reason": "live_state_missing"})
        if result.changed:
            await self.run_effects(match_id, shard_id, state, result.effects)
        return result, state

    async def run_effects(self, match_id: str, shard_id: str, state: dict[str, Any], effects: list[Effect]) -> None:
        for effect in effects:
            try:
                await self._run_effect(match_id, shard_id, state, effect)
            except Exception:  # noqa: BLE001 - effects are recoverable from canonical state
                log.exception("effect_failed", extra={"match_id": match_id, "effect": effect.kind})

    async def _run_effect(self, match_id: str, shard_id: str, state: dict[str, Any], effect: Effect) -> None:
        if effect.kind in _TASK_KINDS:
            parts = tuple(str(p) for p in effect.data.get("dedupe", (match_id,)))
            payload = {"match_id": match_id, "round_id": effect.data.get("round_id"),
                       "expected_state_version": state.get("state_version")}
            await self._c.tasks.schedule(TaskRequest(TaskKind(effect.kind), shard_id, effect.eta_ms, payload, parts))
        elif effect.kind == "SIGN_MEDIA":
            url = await self._c.media_signer.sign(effect.data["path"], effect.data["expires_at_ms"])
            now = self._c.clock.now_ms()
            await self.mutate(match_id, shard_id, lambda s: engine.attach_media(
                s, effect.data["round_id"], url, effect.data["expires_at_ms"], now))
        elif effect.kind == "START_SETTLEMENT":
            await self._c.settlement.start(match_id, shard_id, cancelled=bool(effect.data.get("cancelled")))
        elif effect.kind == "REFILL_QUESTIONS":
            await self._c.survival_refill.refill(match_id, shard_id, effect.data)
        else:
            log.warning("unknown_effect", extra={"effect": effect.kind})

    # ------------------------------------------------------------------------------------------ actions
    async def resolve(self, match_id: str, shard_id: str, source: str) -> dict[str, Any]:
        """``resolve_round_if_due``: shared by every task kind and the sync endpoint (spec §20.4)."""
        now = self._c.clock.now_ms()
        result, state = await self.mutate(match_id, shard_id, lambda s: engine.resolve_due(s, self._keys, now,
                                                                                            source))
        if state.get("state") == MatchState.FINISHED_PENDING_SETTLEMENT and not result.changed:
            # A lost settlement task is rediscovered here (idempotent).
            await self._c.settlement.ensure_scheduled(match_id, shard_id)
        return {"changed": result.changed, "state": state.get("state"), "state_version": state.get("state_version")}

    async def _active_shard(self, uid: str, match_id: str) -> str:
        """Answer path: the caller's active match pointer must equal this match (spec §28.2)."""
        runtime = current(await self._c.store.get(runtime_path(uid)), uid, self._c.clock.now_ms())
        if runtime.get("active_match_id") == match_id and runtime.get("active_shard_id"):
            return runtime["active_shard_id"]
        if runtime.get("pending_settlement_match_id") == match_id:
            raise ApiError(ErrorCode.ROUND_NOT_ACTIVE, status=409)
        raise ApiError(ErrorCode.NOT_MATCH_PARTICIPANT)

    async def answer(self, uid: str, match_id: str, round_id: str, option_id: str, request_id: str,
                     received_at_ms: int, shard_hint: str | None = None) -> dict[str, Any]:
        shard_id = await self._active_shard(uid, match_id)
        if shard_hint and shard_hint != shard_id:
            raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "shard_mismatch"})
        result, state = await self.mutate(match_id, shard_id, lambda s: engine.apply_answer(
            s, self._keys, uid=uid, round_id=round_id, option_id=option_id, received_at_ms=received_at_ms,
            request_id=request_id))
        error = result.outcome.get("error")
        if error:
            code = ErrorCode(error)
            status = 409 if code in (ErrorCode.ROUND_NOT_ACTIVE, ErrorCode.ROUND_EXPIRED,
                                     ErrorCode.ANSWER_ALREADY_SUBMITTED) else None
            raise ApiError(code, status=status, detail={"state_version": state.get("state_version"),
                                                        **({"reason": result.outcome["reason"]}
                                                           if "reason" in result.outcome else {})})
        outcome = {k: v for k, v in result.outcome.items() if k != "accepted"}
        return {"schema_version": 1, "accepted": True, "round_id": round_id, **outcome}

    async def leave(self, uid: str, match_id: str) -> dict[str, Any]:
        idx = await self.index(match_id)
        if uid not in (idx.get("participant_uids") or []):
            raise ApiError(ErrorCode.NOT_MATCH_PARTICIPANT)
        now = self._c.clock.now_ms()
        root = await self._c.live.get(idx["rtdb_shard_id"], f"{root_path(match_id)}/public/state")
        if root is None or root in TERMINAL_STATES:
            return {"schema_version": 1, "left": True, "after_finish": True}
        result, state = await self.mutate(match_id, idx["rtdb_shard_id"],
                                          lambda s: engine.apply_leave(s, self._keys, uid, now))
        if result.outcome.get("error"):
            raise ApiError(ErrorCode(result.outcome["error"]))
        await self._release_leaver(uid, match_id)
        return {"schema_version": 1, "left": True, "state_version": state.get("state_version")}

    async def _release_leaver(self, uid: str, match_id: str) -> None:
        """A leaver waits for the result like everyone else: MATCH_ACTIVE -> SETTLEMENT_PENDING (spec §25.1)."""
        now = self._c.clock.now_ms()

        def txn_fn(txn) -> None:
            runtime = current(txn.get(runtime_path(uid)), uid, now)
            if runtime.get("active_match_id") != match_id:
                return
            txn.set(runtime_path(uid), transition(runtime, RuntimeState.SETTLEMENT_PENDING, now,
                                                  active_match_id=None, pending_settlement_match_id=match_id))

        await self._c.store.run_transaction(txn_fn)

    def _identity_pid(self, identity: str) -> str:
        if identity.startswith("bot:"):
            return self._c.bots.public_id(identity.removeprefix("bot:"))
        return self._c.profiles.public_id(identity)

    async def react(self, uid: str, match_id: str, round_id: str, reaction_id: str) -> dict[str, Any]:
        """Reaction IDs only, never free text; blocked pairs never see each other's reactions (spec §5, §21.6)."""
        idx = await self.index(match_id)
        self._require_viewer(uid, idx)
        if not await self._c.catalog.is_active_reaction(reaction_id):
            raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "reaction_not_allowed"})
        block_pids = {}
        for human in idx.get("participant_uids") or []:
            blocked = await self._c.safety.block_set(human)
            if blocked:
                block_pids[human] = {self._identity_pid(identity) for identity in blocked}
        now = self._c.clock.now_ms()

        def step(state: dict[str, Any]) -> StepResult:
            present = set(state.get("participants") or {})
            mutes = {u: sorted(pids & present) for u, pids in block_pids.items() if pids & present}
            return engine.apply_reaction(state, self._keys, uid=uid, round_id=round_id, reaction_id=reaction_id,
                                         now_ms=now, mutes=mutes)

        result, state = await self.mutate(match_id, idx["rtdb_shard_id"], step)
        error = result.outcome.get("error")
        if error:
            raise ApiError(ErrorCode(error), detail={k: v for k, v in result.outcome.items() if k == "reason"})
        return {"schema_version": 1, **result.outcome}

    async def shown_question(self, uid: str, match_id: str, round_id: str) -> dict[str, Any]:
        """A question the caller actually saw in this match (live state, or history after cleanup)."""
        idx = await self.index(match_id)
        self._require_viewer(uid, idx)
        state = await self._c.live.get(idx["rtdb_shard_id"], f"{root_path(match_id)}/authoritative")
        rounds = list((state or {}).get("round_log") or [])
        if state and (state.get("round") or {}).get("round_id") == round_id:
            rnd = state["round"]
            rounds.append({"round_id": round_id, "qid": rnd["qid"], "gid": rnd["gid"], "v": rnd["v"]})
        if not state:
            history = await self._c.store.get(f"match_history/{match_id}") or {}
            rounds = history.get("round_log") or []
        for entry in rounds:
            if entry.get("round_id") == round_id:
                return {"gid": entry["gid"], "v": entry["v"], "qid": entry.get("qid"), "mode": idx["mode"],
                        "language": idx.get("language", "en")}
        raise ApiError(ErrorCode.NOT_FOUND, detail={"reason": "round_not_in_match"})

    async def sync(self, uid: str, match_id: str) -> dict[str, Any]:
        idx = await self.index(match_id)
        self._require_viewer(uid, idx)
        if idx.get("state") in ("FINISHED", "CANCELLED"):
            return {"schema_version": 1, "state": idx["state"], "changed": False}
        outcome = await self.resolve(match_id, idx["rtdb_shard_id"], "CLIENT_SYNC")
        return {"schema_version": 1, "server_time_ms": self._c.clock.now_ms(), **outcome}

    @staticmethod
    def _require_viewer(uid: str, idx: dict[str, Any]) -> str:
        if uid in (idx.get("participant_uids") or []):
            return "participant"
        if uid in (idx.get("spectator_uids") or []):
            return "spectator"
        raise ApiError(ErrorCode.NOT_MATCH_PARTICIPANT)

    async def view(self, uid: str, match_id: str) -> dict[str, Any]:
        """Reconnect snapshot: the same safe projections a listener would receive."""
        idx = await self.index(match_id)
        role = self._require_viewer(uid, idx)
        shard_id = idx["rtdb_shard_id"]
        public = await self._c.live.get(shard_id, f"{root_path(match_id)}/public")
        private = None
        if role == "participant":
            private = await self._c.live.get(shard_id, f"{root_path(match_id)}/player_private/{uid}")
        return {
            "schema_version": 1,
            "match_id": match_id,
            "mode": idx["mode"],
            "role": role,
            "rtdb_shard_id": shard_id,
            "client_rtdb_url_selector": idx.get("client_rtdb_url_selector", shard_id),
            "rtdb_url": self._c.settings.shard_url(shard_id),
            "index_state": idx.get("state"),
            "server_time_ms": self._c.clock.now_ms(),
            "public": public,
            "player_private": private,
        }
