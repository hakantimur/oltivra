"""Non-public anti-cheat risk score (spec §28.4).

Signals raise a decaying score and preserve bounded evidence; they never ban. Crossing configured thresholds
applies graduated, temporary and reversible restrictions (ranked restriction, then reduced queue access) and
flags the account for human review. Irreversible decisions stay with human moderators.
"""

from __future__ import annotations

import logging
import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import StrEnum
from typing import Any

from app.common.errors import ApiError, ErrorCode
from app.moderation.sanctions import SanctionKind

log = logging.getLogger("oltivra.risk")

DAY_MS = 86_400_000
MAX_EVIDENCE = 20
# Every answer correct with a median below reading time of question + four options is implausible.
ACCURACY_MIN_ANSWERS = 8
ACCURACY_MEDIAN_MS = 600


class RiskSignal(StrEnum):
    FAST_CORRECT = "FAST_CORRECT"  # correct answers accepted faster than humanly plausible
    ACCURACY_SPEED = "ACCURACY_SPEED"  # abnormally high accuracy combined with very low response times
    MALFORMED_REQUEST = "MALFORMED_REQUEST"  # repeated stale/invalid answer submissions
    APP_CHECK_FAILURE = "APP_CHECK_FAILURE"
    QUEUE_MANIPULATION = "QUEUE_MANIPULATION"  # join/leave churn beyond limits
    PURCHASE_ANOMALY = "PURCHASE_ANOMALY"
    REWARD_ANOMALY = "REWARD_ANOMALY"
    ACCOUNT_ABUSE = "ACCOUNT_ABUSE"


WEIGHTS: dict[RiskSignal, float] = {
    RiskSignal.FAST_CORRECT: 10.0,
    RiskSignal.ACCURACY_SPEED: 8.0,
    RiskSignal.MALFORMED_REQUEST: 1.0,
    RiskSignal.APP_CHECK_FAILURE: 3.0,
    RiskSignal.QUEUE_MANIPULATION: 2.0,
    RiskSignal.PURCHASE_ANOMALY: 5.0,
    RiskSignal.REWARD_ANOMALY: 5.0,
    RiskSignal.ACCOUNT_ABUSE: 10.0,
}


def risk_path(uid: str) -> str:
    return f"user_risk/{uid}"


def decayed(score: float, since_ms: int, now_ms: int, half_life_days: float) -> float:
    if score <= 0 or now_ms <= since_ms:
        return max(score, 0.0)
    return score * math.pow(0.5, (now_ms - since_ms) / (half_life_days * DAY_MS))


def match_signals(state: dict[str, Any], uid_by_pid: dict[str, str], fast_ms: int, min_rounds: int
                  ) -> dict[str, list[tuple[RiskSignal, dict[str, Any]]]]:
    """Per-human timing anomalies from the compact round log of one finished match."""
    per_pid: dict[str, list[tuple[bool, int]]] = {}
    for entry in state.get("round_log") or []:
        for pid, answer in (entry.get("answers") or {}).items():
            if pid in uid_by_pid:
                per_pid.setdefault(pid, []).append((bool(answer.get("c")), int(answer.get("ms", 0))))
    out: dict[str, list[tuple[RiskSignal, dict[str, Any]]]] = {}
    for pid, answers in per_pid.items():
        signals = []
        fast = [ms for correct, ms in answers if correct and 0 <= ms < fast_ms]
        if len(fast) >= min_rounds:
            signals.append((RiskSignal.FAST_CORRECT, {"match_id": state["match_id"], "fast_correct": len(fast),
                                                      "min_ms": min(fast)}))
        correct_ms = [ms for correct, ms in answers if correct]
        if (len(answers) >= ACCURACY_MIN_ANSWERS and len(correct_ms) == len(answers)
                and sorted(correct_ms)[len(correct_ms) // 2] < ACCURACY_MEDIAN_MS):
            signals.append((RiskSignal.ACCURACY_SPEED, {"match_id": state["match_id"], "answered": len(answers),
                                                        "median_ms": sorted(correct_ms)[len(correct_ms) // 2]}))
        if signals:
            out[uid_by_pid[pid]] = signals
    return out


@asynccontextmanager
async def watch(container, uid: str | None, signal: RiskSignal, *, codes: set[ErrorCode] | None = None,
                reasons: set[str] | None = None, evidence: dict[str, Any] | None = None) -> AsyncIterator[None]:
    """Record ``signal`` when the wrapped call fails with a matching error, then re-raise unchanged."""
    try:
        yield
    except ApiError as exc:
        reason = (exc.detail or {}).get("reason") if isinstance(exc.detail, dict) else None
        if uid and (codes is None or exc.code in codes) and (reasons is None or reason in reasons):
            try:
                await container.risk.record(uid, signal, evidence={**(evidence or {}), "code": exc.code.value})
            except Exception:  # noqa: BLE001 - risk bookkeeping never changes the caller's outcome
                log.exception("risk_record_failed")
        raise


class RiskService:
    def __init__(self, container) -> None:
        self._c = container

    async def get(self, uid: str) -> dict[str, Any]:
        c = self._c
        doc = await c.store.get(risk_path(uid)) or {}
        config = (await c.config.get()).moderation
        now = c.clock.now_ms()
        return {"uid": uid, "score": round(decayed(float(doc.get("score", 0)), int(doc.get("updated_at_ms", now)),
                                                   now, config.risk_half_life_days), 2),
                "signals": doc.get("signals", {}), "evidence": doc.get("evidence", []),
                "review_required": bool(doc.get("review_required")), "updated_at_ms": doc.get("updated_at_ms")}

    async def record(self, uid: str, signal: RiskSignal, *, count: int = 1,
                     evidence: dict[str, Any] | None = None) -> float:
        c = self._c
        if not uid or uid.startswith("bot:"):
            return 0.0
        config = (await c.config.get()).moderation
        now = c.clock.now_ms()
        path = risk_path(uid)

        def txn_fn(txn) -> dict[str, Any]:
            doc = txn.get(path) or {"schema_version": 1, "uid": uid, "score": 0.0, "signals": {}, "evidence": []}
            score = decayed(float(doc.get("score", 0)), int(doc.get("updated_at_ms", now)), now,
                            config.risk_half_life_days) + WEIGHTS[signal] * count
            signals = dict(doc.get("signals") or {})
            signals[signal.value] = int(signals.get(signal.value, 0)) + count
            items = [*(doc.get("evidence") or []), {"signal": signal.value, "at_ms": now, **(evidence or {})}]
            updated = {**doc, "score": round(score, 3), "signals": signals, "evidence": items[-MAX_EVIDENCE:],
                       "updated_at_ms": now,
                       "review_required": bool(doc.get("review_required")) or score >= config.risk_review_score}
            txn.set(path, updated)
            return updated

        doc = await c.store.run_transaction(txn_fn)
        await self._graduate(uid, float(doc["score"]), config)
        return float(doc["score"])

    async def _graduate(self, uid: str, score: float, config) -> None:
        """Temporary, reversible restrictions only; never an automatic ban (spec §28.4)."""
        c = self._c
        user = await c.store.get(f"users/{uid}")
        if not user:
            return
        now = c.clock.now_ms()
        steps = ((config.risk_ranked_restrict_score, SanctionKind.RANKED_RESTRICTION, config.risk_ranked_restrict_ms,
                  "ranked_restricted_until_ms"),
                 (config.risk_queue_restrict_score, SanctionKind.QUEUE_RESTRICTION, config.risk_queue_restrict_ms,
                  "queue_restricted_until_ms"))
        for threshold, kind, duration, field in steps:
            if score >= threshold and int(user.get(field) or 0) <= now:
                await c.sanctions.apply(uid, kind, actor="risk-engine", reason_code=f"risk_score_{int(score)}",
                                        duration_ms=duration, source="AUTO", evidence={"score": round(score, 2)})

    async def record_match(self, state: dict[str, Any], uid_by_pid: dict[str, str]) -> None:
        config = (await self._c.config.get()).moderation
        found = match_signals(state, uid_by_pid, config.risk_fast_correct_ms, config.risk_fast_correct_min_rounds)
        for uid, signals in found.items():
            for signal, evidence in signals:
                await self.record(uid, signal, evidence=evidence)

    async def clear_review(self, uid: str, actor: str, reason_code: str, reset_score: bool) -> dict[str, Any]:
        c = self._c
        updates: dict[str, Any] = {"review_required": False, "reviewed_by": actor,
                                   "reviewed_at_ms": c.clock.now_ms()}
        if reset_score:
            updates.update({"score": 0.0, "updated_at_ms": c.clock.now_ms()})
        if await c.store.get(risk_path(uid)):
            await c.store.update(risk_path(uid), updates)
        await c.audit.record(actor=actor, action="RISK_REVIEWED", subject=f"user:{uid}", reason_code=reason_code,
                             detail={"reset_score": reset_score})
        return await self.get(uid)
