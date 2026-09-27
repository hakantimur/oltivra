"""Question reports and automatic quarantine (spec §11.3).

One report per user/question-version/reason within the configured period. Automatic quarantine triggers at
>= N unique reporters AND report rate >= R of human impressions; quarantine immediately rebuilds manifests so
the version never reaches a future match. A live round is never replaced mid-round.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from app.common.ids import sha256_hex
from app.common.store.docstore import Increment
from app.questions.models import QuestionStatus
from app.questions.stats import StatIntent

log = logging.getLogger("oltivra.moderation")

STAT_MODES = ("QUICK", "SURVIVAL", "SYNOVA")


class QuestionReportReason(StrEnum):
    WRONG_ANSWER = "WRONG_ANSWER"
    AMBIGUOUS = "AMBIGUOUS"
    OUTDATED = "OUTDATED"
    IMAGE_PROBLEM = "IMAGE_PROBLEM"
    TRANSLATION_PROBLEM = "TRANSLATION_PROBLEM"
    OTHER = "OTHER"


def counter_path(gid: str, version: int) -> str:
    return f"question_report_counters/{gid}_{version}"


class QuestionReportService:
    def __init__(self, container) -> None:
        self._c = container

    async def report(self, uid: str, *, gid: str, version: int, language: str, mode: str,
                     reason: QuestionReportReason, match_id: str | None) -> dict[str, Any]:
        c = self._c
        config = await c.config.get()
        now = c.clock.now_ms()
        window = now // config.moderation.question_report_period_ms
        report_id = sha256_hex(f"{uid}|{gid}|{version}|{reason.value}|{window}")[:32]
        reporter_path = f"question_reporters/{gid}_{version}_{sha256_hex(uid)[:24]}"

        def txn_fn(txn) -> dict[str, Any]:
            existing, reporter, counter = txn.get_many([f"question_reports/{report_id}", reporter_path,
                                                        counter_path(gid, version)])
            if existing:
                return {"duplicate": True, "unique_reporters": (counter or {}).get("unique_reporters", 0)}
            txn.create(f"question_reports/{report_id}", {
                "schema_version": 1, "report_id": report_id, "reporter_uid": uid, "question_group_id": gid,
                "question_version": version, "language": language, "mode": mode, "reason": reason.value,
                "match_id": match_id, "status": "OPEN", "created_at_ms": now})
            unique = int((counter or {}).get("unique_reporters", 0)) + (0 if reporter else 1)
            if not reporter:
                txn.set(reporter_path, {"schema_version": 1, "gid": gid, "version": version, "reporter_uid": uid,
                                        "created_at_ms": now})
            txn.set(counter_path(gid, version), {
                "schema_version": 1, "question_group_id": gid, "question_version": version,
                "reports": Increment(1), "unique_reporters": unique, f"reports_{reason.value.lower()}": Increment(1),
                "updated_at_ms": now}, merge=True)
            return {"duplicate": False, "unique_reporters": unique}

        outcome = await c.store.run_transaction(txn_fn)
        if not outcome["duplicate"]:
            await c.question_stats.apply([StatIntent(gid, version, language, mode, {"report_count": 1})])
            if outcome["unique_reporters"] >= config.moderation.question_quarantine_min_reporters:
                await self.evaluate_quarantine(gid, version)
        return {"schema_version": 1, "accepted": True, "duplicate": outcome["duplicate"]}

    async def impressions(self, gid: str, version: int) -> int:
        config = await self._c.config.get()
        languages = sorted(set(config.features.competitive_languages) | set(config.features.ui_languages))
        total = 0
        for language in languages:
            for mode in STAT_MODES:
                totals = await self._c.question_stats.aggregate(f"{gid}_{version}_{language}_{mode}")
                total += int(totals.get("shown", 0))
        return total

    async def evaluate_quarantine(self, gid: str, version: int) -> bool:
        c = self._c
        config = await c.config.get()
        counter = await c.store.get(counter_path(gid, version)) or {}
        unique = int(counter.get("unique_reporters", 0))
        shown = await self.impressions(gid, version)
        rate = unique / max(shown, 1)
        moderation = config.moderation
        if unique < moderation.question_quarantine_min_reporters or rate < moderation.question_quarantine_rate:
            return False
        group = await c.question_repo.get_group(gid)
        if not group or group.get("version") != version or group.get("status") not in (
                QuestionStatus.ACTIVE.value, QuestionStatus.VERIFIED.value):
            return False
        await c.question_repo.transition(gid, QuestionStatus.QUARANTINED, "auto-quarantine",
                                         f"reports: {unique} unique reporters, rate {rate:.4f}")
        await c.store.set(f"moderation_queue/question_{gid}_{version}", {
            "schema_version": 1, "kind": "QUESTION_QUARANTINE", "question_group_id": gid, "question_version": version,
            "unique_reporters": unique, "impressions": shown, "rate": round(rate, 5), "status": "OPEN",
            "created_at_ms": c.clock.now_ms()})
        languages = sorted(set(config.features.competitive_languages) | set(config.features.ui_languages))
        await c.manifest_builder.build_all(languages)
        c.manifest_cache.invalidate()
        log.warning("question_auto_quarantined", extra={"gid": gid, "version": version})
        return True
