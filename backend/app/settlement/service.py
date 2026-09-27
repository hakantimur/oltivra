"""Match settlement (spec §37): ledger, idempotent persistence, runtime release, live FINISHED, cleanup.

Settlement recomputes only from the immutable final match result and config snapshot stored in the
authoritative live branch, never from current mutable profile data. Progression (XP, MMR, leagues, streaks,
missions, badges, leaderboards) plugs into ``ProgressionHooks``.
"""

from __future__ import annotations

import logging
from typing import Any

from app.accounts.runtime import RuntimeState, current, runtime_path, transition
from app.common.clock import ms_to_datetime
from app.common.tasks import TaskKind, TaskRequest
from app.matches import engine
from app.matches.model import MatchState, humans, participants
from app.matches.service import index_path, root_path

log = logging.getLogger("oltivra.settlement")


def ledger_path(match_id: str) -> str:
    return f"settlement_ledgers/{match_id}"


def history_path(match_id: str) -> str:
    return f"match_history/{match_id}"


class SettlementService:
    def __init__(self, container) -> None:
        self._c = container

    # ------------------------------------------------------------------------------------------ start
    async def start(self, match_id: str, shard_id: str, cancelled: bool = False) -> None:
        """Finish protocol steps 2–3: ledger with a stable idempotency key, runtimes -> SETTLEMENT_PENDING."""
        c = self._c
        now = c.clock.now_ms()

        def txn_fn(txn) -> bool:
            ledger = txn.get(ledger_path(match_id))
            idx = txn.get(index_path(match_id)) or {}
            uids = list(idx.get("participant_uids") or [])
            runtimes = txn.get_many([runtime_path(u) for u in uids]) if uids else []
            if ledger:
                return False
            txn.set(ledger_path(match_id), {
                "schema_version": 1, "match_id": match_id, "rtdb_shard_id": shard_id, "status": "PENDING",
                "idempotency_key": f"settlement:{match_id}", "cancelled": cancelled, "participant_results": {},
                "created_at_ms": now, "completed_at_ms": None, "retry_count": 0})
            if idx:
                txn.update(index_path(match_id), {"state": "CANCELLED_PENDING" if cancelled
                                                  else "FINISHED_PENDING_SETTLEMENT", "finished_at_ms": now})
            for uid, doc in zip(uids, runtimes, strict=True):
                runtime = current(doc, uid, now)
                if runtime.get("active_match_id") == match_id:
                    txn.set(runtime_path(uid), transition(runtime, RuntimeState.SETTLEMENT_PENDING, now,
                                                          active_match_id=None, active_shard_id=shard_id,
                                                          pending_settlement_match_id=match_id))
            return True

        await c.store.run_transaction(txn_fn)
        await self._schedule(match_id, shard_id, attempt=0, eta_ms=now)

    async def _schedule(self, match_id: str, shard_id: str, attempt: int, eta_ms: int) -> None:
        await self._c.tasks.schedule(TaskRequest(TaskKind.SETTLEMENT, shard_id, eta_ms, {"match_id": match_id},
                                                 (match_id, f"a{attempt}")))

    async def ensure_scheduled(self, match_id: str, shard_id: str) -> None:
        ledger = await self._c.store.get(ledger_path(match_id))
        if not ledger:
            await self.start(match_id, shard_id)
        elif ledger["status"] in ("PENDING", "FAILED_RETRYABLE"):
            await self._schedule(match_id, shard_id, int(ledger.get("retry_count", 0)), self._c.clock.now_ms())

    # ------------------------------------------------------------------------------------------ run
    def participant_results(self, state: dict[str, Any], cancelled: bool) -> dict[str, dict[str, Any]]:
        """Immutable per-participant outcome, keyed by uid (humans) or bot_id."""
        result = state.get("result") or {}
        placements = result.get("placements") or {}
        out: dict[str, dict[str, Any]] = {}
        for pid, p in participants(state).items():
            key = p.get("uid") or p["bot_id"]
            out[key] = {
                "pid": pid, "is_bot": p.get("kind") == "BOT", "place": None if cancelled else placements.get(pid),
                "normal_score": p.get("score", 0), "wins": p.get("wins", 0), "left": bool(p.get("left")),
                "correct_rounds": p.get("correct_rounds", 0), "answered_rounds": p.get("answered_rounds", 0),
                "survival_status": p.get("survival_status"), "xp_awarded": 0, "mmr_delta": 0,
            }
        return out

    async def run(self, match_id: str, shard_id: str) -> dict[str, Any]:
        c = self._c
        ledger = await c.store.get(ledger_path(match_id))
        if ledger and ledger["status"] in ("SETTLED", "CANCELLED_NO_PROGRESSION"):
            await self._after_commit(match_id, shard_id, ledger)
            return {"status": ledger["status"], "replay": True}
        state = await c.live.get(shard_id, f"{root_path(match_id)}/authoritative")
        if not state:
            log.error("settlement_live_state_missing", extra={"match_id": match_id})
            await self._record_failure(match_id, "live_state_missing")
            raise RuntimeError("live state missing")
        status = state.get("state")
        if status not in (MatchState.FINISHED_PENDING_SETTLEMENT, MatchState.CANCELLED, MatchState.FINISHED):
            return {"status": "NOT_FINISHED"}
        try:
            ledger = await self._settle(match_id, shard_id, state)
        except Exception as exc:
            retries = await self._record_failure(match_id, type(exc).__name__)
            max_retries = int((state.get("config") or {}).get("retention", {}).get("settlement_max_retries", 8))
            if retries >= max_retries:
                # Keep "Finalising Results" and the runtime lock; operations is alerted (spec §37.2).
                log.critical("settlement_retries_exhausted", extra={"match_id": match_id})
            raise
        await self._after_commit(match_id, shard_id, ledger)
        return {"status": ledger["status"], "replay": False}

    async def _record_failure(self, match_id: str, reason: str) -> int:
        now = self._c.clock.now_ms()

        def txn_fn(txn) -> int:
            ledger = txn.get(ledger_path(match_id)) or {"match_id": match_id, "retry_count": 0}
            if ledger.get("status") in ("SETTLED", "CANCELLED_NO_PROGRESSION"):
                return int(ledger.get("retry_count", 0))
            retries = int(ledger.get("retry_count", 0)) + 1
            txn.set(ledger_path(match_id), {**ledger, "status": "FAILED_RETRYABLE", "retry_count": retries,
                                            "last_error": reason, "updated_at_ms": now})
            return retries

        return await self._c.store.run_transaction(txn_fn)

    async def _settle(self, match_id: str, shard_id: str, state: dict[str, Any]) -> dict[str, Any]:
        c = self._c
        now = c.clock.now_ms()
        cancelled = state.get("state") == MatchState.CANCELLED
        results = self.participant_results(state, cancelled)
        human_uids = [p["uid"] for p in humans(state).values()]
        shown = [int(q) for q in state.get("shown_qids") or []]
        hooks = getattr(c, "progression", None)

        def txn_fn(txn) -> dict[str, Any]:
            ledger = txn.get(ledger_path(match_id)) or {}
            runtimes = txn.get_many([runtime_path(u) for u in human_uids])
            exposures = txn.get_many([c.exposure.path(u) for u in human_uids])
            users = txn.get_many([f"users/{u}" for u in human_uids])
            prepared = hooks.read(txn, state, results, dict(zip(human_uids, users, strict=True))) if hooks else None
            if ledger.get("status") in ("SETTLED", "CANCELLED_NO_PROGRESSION"):
                return ledger
            if hooks and not cancelled:
                hooks.apply(txn, state, results, prepared, now)
            final_status = "CANCELLED_NO_PROGRESSION" if cancelled else "SETTLED"
            txn.set(history_path(match_id), self._history_doc(match_id, state, results, cancelled, now))
            for uid, exposure in zip(human_uids, exposures, strict=True):
                if shown:
                    c.exposure.append_in_txn(txn, uid, shown, exposure)
            for uid, doc in zip(human_uids, runtimes, strict=True):
                runtime = current(doc, uid, now)
                if match_id not in (runtime.get("pending_settlement_match_id"), runtime.get("active_match_id")):
                    continue
                if runtime.get("deletion_requested"):
                    txn.set(runtime_path(uid), transition(runtime, RuntimeState.DELETION_PENDING, now,
                                                          deletion_requested=True))
                else:
                    txn.set(runtime_path(uid), transition(runtime, RuntimeState.IDLE, now))
            done = {**ledger, "schema_version": 1, "match_id": match_id, "rtdb_shard_id": shard_id,
                    "status": final_status, "idempotency_key": f"settlement:{match_id}",
                    "participant_results": results, "completed_at_ms": now,
                    "deletion_uids": [u for u, d in zip(human_uids, runtimes, strict=True)
                                      if d and d.get("deletion_requested")]}
            txn.set(ledger_path(match_id), done)
            txn.update(index_path(match_id), {"state": "CANCELLED" if cancelled else "FINISHED",
                                              "settled_at_ms": now})
            return done

        return await c.store.run_transaction(txn_fn)

    @staticmethod
    def _history_doc(match_id: str, state: dict[str, Any], results: dict[str, dict[str, Any]], cancelled: bool,
                     now: int) -> dict[str, Any]:
        ranked = state.get("ranked") or {}
        ordered = sorted(results.items(), key=lambda kv: (kv[1]["place"] is None, kv[1]["place"] or 0))
        return {
            "schema_version": 1,
            "match_id": match_id,
            "mode": state["mode"],
            "region": state["region"],
            "language": state["language"],
            "source": state.get("source"),
            "config_version": (state.get("config") or {}).get("config_version", 1),
            "ranked_eligible": bool(ranked.get("eligible")) and not cancelled,
            "human_slot_count": ranked.get("human_slots", 0),
            "bot_slot_count": ranked.get("bot_slots", 0),
            "cancelled": cancelled,
            "cancel_reason": state.get("cancel_reason"),
            "participant_uids": [k for k, r in results.items() if not r["is_bot"]],
            "participants": [{"uid_or_bot_id": key, **r} for key, r in ordered],
            "question_versions": [{"question_group_id": r["gid"], "version": r["v"], "language": state["language"],
                                   "qid": r["qid"]} for r in state.get("round_log") or []],
            "round_log": state.get("round_log") or [],
            "sudden_death": (state.get("result") or {}).get("sudden_death"),
            "completed_at_ms": now,
            "completed_at": ms_to_datetime(now),
        }

    async def _after_commit(self, match_id: str, shard_id: str, ledger: dict[str, Any]) -> None:
        """Steps 7–8 plus deferred account deletions. Each step is idempotent."""
        c = self._c
        now = c.clock.now_ms()
        by_uid = {uid: {k: r[k] for k in ("place", "xp_awarded", "mmr_delta") if k in r}
                  | {k: r[k] for k in r if k.startswith("progress_")}
                  for uid, r in (ledger.get("participant_results") or {}).items() if not r.get("is_bot")}
        try:
            await c.matches.mutate(match_id, shard_id, lambda s: engine.mark_settled(s, now, ledger["status"],
                                                                                      by_uid))
        except Exception:  # noqa: BLE001 - live root may already be cleaned
            log.info("settlement_live_mark_skipped", extra={"match_id": match_id})
        if not ledger.get("room_closed"):
            await c.shard_admission.room_closed(shard_id, now)
            await c.store.update(ledger_path(match_id), {"room_closed": True})
        retention = (await c.config.get()).retention.live_cleanup_after_settlement_ms
        await c.tasks.schedule(TaskRequest(TaskKind.CLEANUP, shard_id, now + retention, {"match_id": match_id},
                                           (match_id,)))
        for uid in ledger.get("deletion_uids") or []:
            await c.deletion.complete(uid)

    # ------------------------------------------------------------------------------------------ cleanup / abort
    async def cleanup(self, match_id: str, shard_id: str) -> dict[str, Any]:
        """Remove live state only after settlement succeeded (spec §17.5)."""
        ledger = await self._c.store.get(ledger_path(match_id))
        if not ledger or ledger["status"] not in ("SETTLED", "CANCELLED_NO_PROGRESSION"):
            return {"deleted": False}
        await self._c.live.delete(shard_id, root_path(match_id))
        return {"deleted": True}

    async def abort_unstarted(self, match_id: str, reason: str) -> None:
        """The claim committed but the live root could not be created: release everyone (spec §37.3)."""
        c = self._c
        now = c.clock.now_ms()

        def txn_fn(txn) -> str | None:
            idx = txn.get(index_path(match_id))
            if not idx:
                return None
            uids = list(idx.get("participant_uids") or [])
            runtimes = txn.get_many([runtime_path(u) for u in uids])
            txn.update(index_path(match_id), {"state": "CANCELLED", "cancel_reason": reason, "settled_at_ms": now})
            txn.set(ledger_path(match_id), {"schema_version": 1, "match_id": match_id, "status":
                                            "CANCELLED_NO_PROGRESSION", "cancel_reason": reason,
                                            "idempotency_key": f"settlement:{match_id}", "participant_results": {},
                                            "created_at_ms": now, "completed_at_ms": now, "retry_count": 0,
                                            "room_closed": True})
            for uid, doc in zip(uids, runtimes, strict=True):
                runtime = current(doc, uid, now)
                if match_id in (runtime.get("active_match_id"), runtime.get("pending_settlement_match_id")):
                    txn.set(runtime_path(uid), transition(runtime, RuntimeState.IDLE, now))
            return idx["rtdb_shard_id"]

        shard_id = await c.store.run_transaction(txn_fn)
        if shard_id:
            await c.shard_admission.room_closed(shard_id, now)
