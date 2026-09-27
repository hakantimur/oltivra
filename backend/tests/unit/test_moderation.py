"""Sanctions, risk score and admin moderation queues (spec §11, §28.4, §29)."""

from __future__ import annotations

import asyncio

import pytest

from app.common.errors import ApiError, ErrorCode
from app.moderation.risk import RiskSignal, match_signals, watch
from app.moderation.sanctions import SanctionKind, summarize
from tests.unit.test_matchmaking import answer, bot_fill_match, join, public, run_tasks
from tests.unit.test_progression import ranked_match, user

ADMIN = "admin1"
AS_ADMIN = ":admin:mfa"
HOUR = 3_600_000


@pytest.fixture
def players(api):
    for uid in ("u1", "u2", "u3", "u4"):
        api.onboard(uid)
    return api


def sanction(api, ref, kind, duration_ms=None, **extra):
    body = {"kind": kind, "reason_code": "test_reason", "duration_ms": duration_ms, **extra}
    return api.post(f"/admin/v1/users/{ref}/sanctions", ADMIN, body, extra=AS_ADMIN)


def play_fast_round(api, container, match_id, uid="u1", after_ms=120):
    pub = public(container, match_id)
    container.clock.set(pub["starts_at_ms"])
    run_tasks(container)
    container.clock.advance(after_ms)
    assert answer(api, container, match_id, uid).status_code == 200
    pub = public(container, match_id)
    container.clock.set(pub["reveal_ends_at_ms"] + 50)
    run_tasks(container)


# ---------------------------------------------------------------------------------------------- sanctions


def test_suspension_blocks_requests_until_it_ends(players, container):
    res = sanction(players, "u1", "SUSPEND", HOUR)
    assert res.status_code == 200, res.text
    assert res.json()["sanction"]["summary"]["status"] == "SUSPENDED"
    blocked = players.get("/v1/profile", "u1")
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "ACCOUNT_SUSPENDED"
    container.clock.advance(HOUR + 1)
    assert players.get("/v1/profile", "u1").status_code == 200
    assert asyncio.run(container.sanctions.expire_due()) == 1
    assert user(container, "u1")["status"] == "ACTIVE"


def test_suspension_requires_duration_and_cancels_queue(players, container):
    assert sanction(players, "u1", "SUSPEND").json()["error"]["detail"]["reason"] == "duration_required"
    assert join(players, "u1").json()["state"] == "QUEUED"
    sanction(players, "u1", "SUSPEND", HOUR)
    assert container.store._docs["user_runtime/u1"]["state"] == "IDLE"


def test_ban_needs_confirmation_and_cannot_be_lifted(players, container):
    res = sanction(players, "u2", "BAN")
    assert res.json()["error"]["detail"]["reason"] == "confirm_irreversible_required"
    res = sanction(players, "u2", "BAN", confirm_irreversible=True)
    ban = res.json()["sanction"]
    assert ban["ends_at_ms"] is None and ban["reversible"] is False
    assert players.get("/v1/profile", "u2").status_code == 403
    lift = players.post(f"/admin/v1/sanctions/{ban['sanction_id']}/lift", ADMIN, {"reason_code": "appeal"},
                        extra=AS_ADMIN)
    assert lift.status_code == 409
    audit = players.get("/admin/v1/audit", ADMIN, extra=AS_ADMIN, subject="user:u2").json()["entries"]
    assert audit[0]["action"] == "SANCTION_BAN" and audit[0]["reversible"] is False


def test_rename_required_blocks_queue_until_rename(players, container):
    sanction(players, "u1", "RENAME_REQUIRED")
    res = join(players, "u1")
    assert res.status_code == 403 and res.json()["error"]["code"] == "RENAME_REQUIRED"
    assert players.get("/v1/profile", "u1").status_code == 200  # the account itself stays usable
    # The 30-day username cooldown does not apply to a forced rename.
    container.clock.advance(1000)
    res = players.post("/v1/profile/username/change", "u1", {"username": "fresh_name"})
    assert res.status_code == 200, res.text
    assert join(players, "u1").json()["state"] == "QUEUED"
    # Recomputing the summary later keeps the satisfied rename sanction inactive.
    asyncio.run(container.sanctions._recompute("u1"))
    assert user(container, "u1")["rename_required"] is False


def test_queue_restriction_and_lift(players, container):
    applied = sanction(players, "u1", "QUEUE_RESTRICTION", HOUR).json()["sanction"]
    res = join(players, "u1")
    assert res.status_code == 403 and res.json()["error"]["code"] == "QUEUE_RESTRICTED"
    assert res.json()["error"]["detail"]["available_at_ms"] == applied["ends_at_ms"]
    lift = players.post(f"/admin/v1/sanctions/{applied['sanction_id']}/lift", ADMIN, {"reason_code": "mistake"},
                        extra=AS_ADMIN)
    assert lift.json()["sanction"]["state"] == "LIFTED"
    assert join(players, "u1").json()["state"] == "QUEUED"


def test_ranked_restriction_keeps_mmr_but_awards_xp(players, container):
    sanction(players, "u1", "RANKED_RESTRICTION", 24 * HOUR)
    match_id = ranked_match(players, container)
    from tests.unit.test_matchmaking import play_round_human_wins

    for _ in range(10):
        play_round_human_wins(players, container, match_id, uid="u1")
    u1 = user(container, "u1")
    assert u1["mmr"] == 1000 and u1["ranked_matches_completed"] == 0 and u1["total_xp"] == 150
    assert user(container, "u2")["ranked_matches_completed"] == 1  # others are unaffected


def test_sanctions_are_admin_only_and_bots_excluded(players, container):
    res = players.post("/admin/v1/users/u2/sanctions", "u1", {"kind": "BAN", "reason_code": "grief"})
    assert res.status_code == 403
    with pytest.raises(ApiError):
        asyncio.run(container.sanctions.apply("bot:b001", SanctionKind.SUSPEND, actor="a", reason_code="x",
                                              duration_ms=HOUR))
    with pytest.raises(ApiError) as exc:
        asyncio.run(container.sanctions.apply("u1", SanctionKind.BAN, actor="risk", reason_code="x",
                                              duration_ms=None, source="AUTO"))
    assert exc.value.code == ErrorCode.FORBIDDEN


def test_summarize_preserves_deletion_state():
    sanctions = [{"kind": "SUSPEND", "state": "ACTIVE", "created_at_ms": 1, "ends_at_ms": 10_000}]
    assert summarize(sanctions, {"status": "DELETION_PENDING"}, 5)["status"] == "DELETION_PENDING"
    assert summarize(sanctions, {"status": "ACTIVE"}, 5)["status"] == "SUSPENDED"
    assert summarize(sanctions, {"status": "SUSPENDED"}, 20_000)["status"] == "ACTIVE"


# ---------------------------------------------------------------------------------------------- risk


def test_match_signals_detect_fast_correct_and_accuracy_speed():
    state = {"match_id": "m1", "round_log": [
        {"answers": {"p1": {"c": True, "ms": 150}, "p2": {"c": True, "ms": 2500}, "p3": {"c": True, "ms": 100}}}
        for _ in range(8)]}
    found = match_signals(state, {"p1": "u1", "p2": "u2"}, fast_ms=300, min_rounds=3)
    assert {s for s, _ in found["u1"]} == {RiskSignal.FAST_CORRECT, RiskSignal.ACCURACY_SPEED}
    assert "u2" not in found and len(found) == 1  # p3 is not a human (bot answers are ignored)


def test_risk_graduates_to_temporary_restrictions_never_ban(players, container):
    for _ in range(4):
        asyncio.run(container.risk.record("u1", RiskSignal.FAST_CORRECT, evidence={"match_id": "m"}))
    u1 = user(container, "u1")
    assert u1["ranked_restricted_until_ms"] > container.clock.now_ms() and u1["status"] == "ACTIVE"
    assert not u1.get("queue_restricted_until_ms")
    for _ in range(4):
        asyncio.run(container.risk.record("u1", RiskSignal.FAST_CORRECT))
    u1 = user(container, "u1")
    assert u1["queue_restricted_until_ms"] > container.clock.now_ms() and u1["status"] == "ACTIVE"
    kinds = [s["kind"] for s in asyncio.run(container.sanctions.list_for("u1"))]
    assert sorted(kinds) == ["QUEUE_RESTRICTION", "RANKED_RESTRICTION"]
    risk = asyncio.run(container.risk.get("u1"))
    assert risk["review_required"] and risk["signals"]["FAST_CORRECT"] == 8 and len(risk["evidence"]) == 8


def test_risk_score_decays(players, container):
    asyncio.run(container.risk.record("u1", RiskSignal.PURCHASE_ANOMALY))
    container.clock.advance(14 * 86_400_000)
    assert asyncio.run(container.risk.get("u1"))["score"] == pytest.approx(2.5)


def test_settlement_records_fast_answers_once(players, container):
    match_id = bot_fill_match(players, container)
    for _ in range(10):
        play_fast_round(players, container, match_id)
    risk = asyncio.run(container.risk.get("u1"))
    assert risk["signals"] == {"FAST_CORRECT": 1, "ACCURACY_SPEED": 1}
    ledger = container.store._docs[f"settlement_ledgers/{match_id}"]
    assert ledger["risk_recorded"] is True
    asyncio.run(container.settlement.run(match_id, ledger["rtdb_shard_id"]))  # replay is harmless
    assert asyncio.run(container.risk.get("u1"))["signals"]["FAST_CORRECT"] == 1


def test_watch_records_only_matching_errors(players, container):
    async def scenario():
        with pytest.raises(ApiError):
            async with watch(container, "u1", RiskSignal.APP_CHECK_FAILURE, codes={ErrorCode.APP_CHECK_FAILED}):
                raise ApiError(ErrorCode.APP_CHECK_FAILED)
        with pytest.raises(ApiError):
            async with watch(container, "u1", RiskSignal.APP_CHECK_FAILURE, codes={ErrorCode.APP_CHECK_FAILED}):
                raise ApiError(ErrorCode.NOT_FOUND)
        return await container.risk.get("u1")

    assert asyncio.run(scenario())["signals"] == {"APP_CHECK_FAILURE": 1}


def test_queue_churn_rate_limit_feeds_risk(players, container):
    codes = []
    for _ in range(5):
        codes.append(join(players, "u1").status_code)
        players.post("/v1/matchmaking/quick/leave", "u1", {})
    assert 429 in codes
    assert asyncio.run(container.risk.get("u1"))["signals"].get("QUEUE_MANIPULATION", 0) >= 1


def test_risk_review_queue(players, container):
    for _ in range(3):
        asyncio.run(container.risk.record("u2", RiskSignal.FAST_CORRECT))
    queue = players.get("/admin/v1/risk", ADMIN, extra=AS_ADMIN).json()["items"]
    assert [i["uid"] for i in queue] == ["u2"] and queue[0]["user"]["username"] == "user_u2"
    res = players.post("/admin/v1/users/u2/risk/review", ADMIN, {"reason_code": "false_positive",
                                                                  "reset_score": True}, extra=AS_ADMIN)
    assert res.json()["risk"]["score"] == 0 and not res.json()["risk"]["review_required"]
    assert players.get("/admin/v1/risk", ADMIN, extra=AS_ADMIN).json()["items"] == []


# ---------------------------------------------------------------------------------------------- queues


def test_player_report_queue_and_resolution(players, container):
    target = container.profiles.public_id("u2")
    for reporter in ("u1", "u3"):
        res = players.post("/v1/player-reports", reporter, {"target_public_id": target,
                                                           "reason": "OFFENSIVE_USERNAME"})
        assert res.status_code == 200
    queue = players.get("/admin/v1/player-reports", ADMIN, extra=AS_ADMIN).json()["items"]
    assert len(queue) == 2 and queue[0]["open_reports_against_target"] == 2
    assert queue[0]["target"]["public_id"] == target
    first, second = queue
    res = players.post(f"/admin/v1/player-reports/{first['report_id']}/resolve", ADMIN,
                       {"action": "SANCTION", "reason_code": "offensive_name",
                        "sanction": {"kind": "RENAME_REQUIRED", "reason_code": "offensive_name"}}, extra=AS_ADMIN)
    assert res.json()["status"] == "RESOLVED" and user(container, "u2")["rename_required"] is True
    res = players.post(f"/admin/v1/player-reports/{second['report_id']}/resolve", ADMIN,
                       {"action": "DISMISS", "reason_code": "duplicate"}, extra=AS_ADMIN)
    assert res.json()["status"] == "DISMISSED"
    again = players.post(f"/admin/v1/player-reports/{second['report_id']}/resolve", ADMIN,
                         {"action": "DISMISS", "reason_code": "duplicate"}, extra=AS_ADMIN)
    assert again.status_code == 409
    assert players.get("/admin/v1/player-reports", ADMIN, extra=AS_ADMIN).json()["items"] == []


def test_question_report_queue_quarantine_and_restore(players, container):
    match_id = bot_fill_match(players, container)
    pub = public(container, match_id)
    container.clock.set(pub["starts_at_ms"])
    run_tasks(container)
    res = players.post(f"/v1/matches/{match_id}/question-report", "u1",
                       {"round_id": pub["round_id"], "reason": "WRONG_ANSWER"})
    assert res.status_code == 200, res.text
    queue = players.get("/admin/v1/question-reports", ADMIN, extra=AS_ADMIN).json()["items"]
    assert len(queue) == 1 and queue[0]["by_reason"] == {"WRONG_ANSWER": 1}
    gid, version = queue[0]["question_group_id"], queue[0]["question_version"]
    detail = players.get(f"/admin/v1/question-reports/{gid}/{version}", ADMIN, extra=AS_ADMIN).json()
    assert detail["reports"][0]["reason"] == "WRONG_ANSWER" and "reporter_uid" not in detail["reports"][0]
    res = players.post(f"/admin/v1/question-reports/{gid}/{version}/resolve", ADMIN,
                       {"action": "QUARANTINE", "reason_code": "answer_wrong"}, extra=AS_ADMIN)
    assert res.json()["status"] == "QUARANTINED" and res.json()["resolved_reports"] == 1
    assert players.get("/admin/v1/question-reports", ADMIN, extra=AS_ADMIN).json()["items"] == []
    res = players.post(f"/admin/v1/question-reports/{gid}/{version}/resolve", ADMIN,
                       {"action": "RESTORE", "reason_code": "fixed_source"}, extra=AS_ADMIN)
    assert res.json()["status"] == "ACTIVE"


def test_user_view_and_search(players, container):
    sanction(players, "u3", "QUEUE_RESTRICTION", HOUR)
    found = players.get("/admin/v1/users", ADMIN, extra=AS_ADMIN, q="user_u").json()["items"]
    assert {f["uid"] for f in found} == {"u1", "u2", "u3", "u4"}  # bots are excluded
    public_id = container.profiles.public_id("u3")
    view = players.get(f"/admin/v1/users/{public_id}", ADMIN, extra=AS_ADMIN).json()
    assert view["user"]["uid"] == "u3" and view["sanctions"][0]["kind"] == "QUEUE_RESTRICTION"
    assert view["risk"]["score"] == 0 and view["runtime"] is None or view["runtime"]["state"] == "IDLE"
    assert players.get("/admin/v1/users/nobody", ADMIN, extra=AS_ADMIN).status_code == 404


def test_late_answers_are_normal_play_but_stale_and_forged_ones_count(players, container):
    match_id = bot_fill_match(players, container)
    pub = public(container, match_id)
    container.clock.set(pub["starts_at_ms"])
    run_tasks(container)
    container.clock.advance(500)
    assert answer(players, container, match_id, "u1").status_code == 200
    # A second answer after the round closed (normal network race) is rejected but not a risk signal.
    late = players.post(f"/v1/matches/{match_id}/answer", "u1",
                        {"round_id": pub["round_id"], "option_id": "whatever"})
    assert late.status_code in (409, 400)
    stale = players.post(f"/v1/matches/{match_id}/answer", "u1", {"round_id": "r_old", "option_id": "x"})
    assert stale.status_code == 409 and stale.json()["error"]["detail"]["reason"] == "stale_round"
    signals = asyncio.run(container.risk.get("u1"))["signals"]
    assert signals == {"MALFORMED_REQUEST": 1}
