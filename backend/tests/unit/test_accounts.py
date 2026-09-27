from __future__ import annotations

import threading

import pytest

from app.accounts.runtime import RuntimeState, idle_runtime, require_idle, transition
from app.common.errors import ApiError, ErrorCode
from app.profiles.service import PRIVACY_VERSION, TERMS_VERSION, USERNAME_COOLDOWN_MS
from app.ranking.leagues import League, display_league, league_for_mmr, league_progress
from app.ranking.levels import level_for_xp, xp_to_start_level
from app.usernames.rules import UsernameProblem, check_username

# ---------------------------------------------------------------- pure rules


@pytest.mark.parametrize("name,problem", [
    ("ab", UsernameProblem.FORMAT),
    ("a" * 17, UsernameProblem.FORMAT),
    ("has space", UsernameProblem.FORMAT),
    ("naïve", UsernameProblem.FORMAT),
    ("Admin", UsernameProblem.RESERVED),
    ("oltivra_team", UsernameProblem.RESERVED),
    ("real_Moderator", UsernameProblem.RESERVED),
    ("sh1t_happens", UsernameProblem.PROFANITY),
    ("fuuuck", UsernameProblem.PROFANITY),
    ("mira_moves", None),
    ("Grape_Juice", None),
    ("Peacock99", None),
])
def test_username_rules(name, problem):
    assert check_username(name) == problem


def test_level_curve():
    assert xp_to_start_level(1) == 0
    assert xp_to_start_level(2) == 100
    assert xp_to_start_level(3) == round(100 * 2 ** 1.6)
    assert level_for_xp(0) == 1 and level_for_xp(99) == 1 and level_for_xp(100) == 2
    assert level_for_xp(xp_to_start_level(12)) == 12


@pytest.mark.parametrize("mmr,league", [
    (899, League.BRONZE), (900, League.SILVER), (1049, League.SILVER), (1050, League.GOLD),
    (1200, League.PLATINUM), (1350, League.DIAMOND), (1500, League.MASTER), (1699, League.MASTER),
    (1700, League.LEGEND),
])
def test_league_thresholds(mmr, league):
    assert league_for_mmr(mmr) == league


def test_unranked_during_placement_and_no_raw_mmr_in_progress():
    assert display_league(1400, 4) == League.UNRANKED
    progress = league_progress(1100, 7)
    assert progress["league"] == "GOLD" and 0 <= progress["progress"] <= 1
    assert "mmr" not in progress


def test_runtime_lock_rules():
    runtime = idle_runtime("u", 0)
    require_idle(runtime)
    queued = transition(runtime, RuntimeState.QUEUED, 1, active_ticket_id="t1")
    with pytest.raises(ApiError) as err:
        require_idle(queued)
    assert err.value.code == ErrorCode.ACTIVE_RUNTIME_CONFLICT
    pending = transition(queued, RuntimeState.SETTLEMENT_PENDING, 2)
    with pytest.raises(ApiError) as err:
        require_idle(pending)
    assert err.value.code == ErrorCode.MATCH_SETTLEMENT_PENDING
    back = transition(pending, RuntimeState.IDLE, 3)
    assert back["active_ticket_id"] is None and back["lock_version"] == 3


# ---------------------------------------------------------------- onboarding API


def test_first_run_flow_and_bootstrap(api):
    res = api.post("/v1/session/bootstrap", "new1", {"client_time_ms": 1})
    assert res.status_code == 200
    assert res.json()["account"]["onboarding"] == {"consent": False, "username": False, "avatar": False,
                                                    "rename_required": False}
    profile = api.onboard("new1", "Mira_Moves")
    assert profile["username_display"] == "Mira_Moves"
    assert profile["onboarding"] == {"consent": True, "username": True, "avatar": True, "rename_required": False}
    assert profile["league"] == "UNRANKED" and profile["level"] == 1
    body = api.post("/v1/session/bootstrap", "new1", {}).json()
    assert body["profile"]["public_id"].startswith("p")
    assert body["runtime"]["state"] == "IDLE"
    dumped = str(body)
    assert "mmr" not in dumped.replace("mmr_", "")


def test_consent_requires_age_gate_and_current_versions(api):
    res = api.post("/v1/onboarding/consent", "u", {"age_gate_confirmed": False, "terms_version": TERMS_VERSION,
                                                    "privacy_version": PRIVACY_VERSION})
    assert res.status_code == 400
    res = api.post("/v1/onboarding/consent", "u", {"age_gate_confirmed": True, "terms_version": "2020-01",
                                                    "privacy_version": PRIVACY_VERSION})
    assert res.json()["error"]["detail"]["reason"] == "legal_version_outdated"


def test_consent_stores_no_date_of_birth(api, container):
    api.onboard("dob1")
    user = container.store.dump("users")["users/dob1"]
    assert user["age_gate_passed"] is True
    assert not any("birth" in k or "dob" in k for k in user)


def test_username_uniqueness_is_case_insensitive(api):
    api.onboard("a1", "QuizKing")
    api.post("/v1/onboarding/consent", "a2", {"age_gate_confirmed": True, "terms_version": TERMS_VERSION,
                                               "privacy_version": PRIVACY_VERSION})
    res = api.post("/v1/profile/username", "a2", {"username": "quizking"})
    assert res.json()["error"]["code"] == "USERNAME_TAKEN"
    res = api.get("/v1/usernames/availability", "a2", username="QUIZKING")
    assert res.json() == {"schema_version": 1, "available": False, "reason": "TAKEN"}
    assert api.get("/v1/usernames/availability", "a2", username="Admin").json()["reason"] == "RESERVED"


def test_concurrent_username_claims_have_one_winner(container):
    import asyncio

    uids = [f"r{i}" for i in range(8)]

    async def prep():
        for uid in uids:
            await container.profiles.record_consent(uid, True, TERMS_VERSION, PRIVACY_VERSION)

    asyncio.run(prep())
    results: list[str] = []

    def attempt(uid: str) -> None:
        try:
            asyncio.run(container.profiles.claim_username(uid, "SameName", change=False))
            results.append("ok")
        except ApiError as err:
            results.append(err.code.value)

    threads = [threading.Thread(target=attempt, args=(u,)) for u in uids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 1
    assert results.count("USERNAME_TAKEN") == 7


def test_username_change_cooldown_and_reservation(api, clock):
    api.onboard("c1", "FirstName")
    res = api.post("/v1/profile/username/change", "c1", {"username": "SecondName"})
    assert res.json()["error"]["code"] == "USERNAME_COOLDOWN"
    clock.advance(USERNAME_COOLDOWN_MS)
    res = api.post("/v1/profile/username/change", "c1", {"username": "SecondName"})
    assert res.status_code == 200 and res.json()["profile"]["username_display"] == "SecondName"
    # The previous name stays reserved for 30 days against other users.
    api.post("/v1/onboarding/consent", "c2", {"age_gate_confirmed": True, "terms_version": TERMS_VERSION,
                                               "privacy_version": PRIVACY_VERSION})
    assert api.post("/v1/profile/username", "c2", {"username": "firstname"}).json()["error"]["code"] == \
        "USERNAME_TAKEN"
    clock.advance(USERNAME_COOLDOWN_MS + 1)
    assert api.post("/v1/profile/username", "c2", {"username": "firstname"}).status_code == 200


def test_avatar_must_be_in_active_catalog(api):
    api.onboard("av1")
    res = api.patch("/v1/profile/avatar", "av1", {"avatar_id": "uploaded_photo"})
    assert res.json()["error"]["detail"]["reason"] == "avatar_not_in_catalog"
    assert len(api.get("/v1/avatars", "av1").json()["avatars"]) == 12


def test_reaction_catalog_localised(api):
    items = api.get("/v1/reactions", "x", lang="tr").json()["reactions"]
    assert len(items) == 10 and {"id": "text_gg", "kind": "TEXT", "display": "GG!", "label": "İyi oyun!"} in items


def test_question_language_never_falls_back(api):
    api.onboard("lang1")
    res = api.patch("/v1/profile/preferences", "lang1", {"question_language": "tr", "ui_language": "tr"})
    assert res.json()["error"]["code"] == "FEATURE_DISABLED"
    res = api.patch("/v1/profile/preferences", "lang1", {"ui_language": "tr"})
    assert res.json()["profile"]["ui_language"] == "tr" and res.json()["profile"]["question_language"] == "en"


def test_cosmetics_only_if_earned(api):
    api.onboard("cos1")
    res = api.patch("/v1/profile/cosmetics", "cos1", {"frame_id": "frame_legend"})
    assert res.json()["error"]["detail"]["reason"] == "frame_not_earned"


def test_player_endpoints_require_completed_profile(api):
    api.post("/v1/onboarding/consent", "half", {"age_gate_confirmed": True, "terms_version": TERMS_VERSION,
                                                 "privacy_version": PRIVACY_VERSION})
    assert api.get("/v1/blocks", "half").json()["error"]["code"] == "PROFILE_INCOMPLETE"


# ---------------------------------------------------------------- safety


def test_block_unblock_and_list(api):
    api.onboard("b1", "Blocker")
    target = api.onboard("b2", "Target")
    assert api.post(f"/v1/blocks/{target['public_id']}", "b1").json()["blocked"] is True
    listed = api.get("/v1/blocks", "b1").json()["blocked"]
    assert listed == [{"public_id": target["public_id"], "username": "Target", "avatar_id": "av_001"}]
    assert api.delete(f"/v1/blocks/{target['public_id']}", "b1").json()["blocked"] is False
    assert api.get("/v1/blocks", "b1").json()["blocked"] == []


def test_player_report_rate_limited(api):
    api.onboard("rep1")
    target = api.onboard("rep2")
    for _ in range(10):
        res = api.post("/v1/player-reports", "rep1", {"target_public_id": target["public_id"],
                                                       "reason": "OFFENSIVE_USERNAME"})
        assert res.status_code == 200
    res = api.post("/v1/player-reports", "rep1", {"target_public_id": target["public_id"], "reason": "OTHER"})
    assert res.json()["error"]["code"] == "RATE_LIMITED"


def test_suspended_account_rejected(api, container):
    api.onboard("sus1")
    container.store.run_transaction_sync(lambda t: t.update("users/sus1", {"status": "SUSPENDED"}))
    assert api.get("/v1/profile", "sus1").json()["error"]["code"] == "ACCOUNT_SUSPENDED"


# ---------------------------------------------------------------- deletion


def test_deletion_requires_recent_login(api):
    api.onboard("del0")
    res = api.delete("/v1/account", "del0")
    assert res.json()["error"]["detail"]["reason"] == "recent_login_required"


def test_idle_account_deletion_end_to_end(api, container):
    me = api.onboard("del1", "LeavingSoon")
    other = api.onboard("del2", "Stayer")
    api.post(f"/v1/blocks/{other['public_id']}", "del1")
    res = api.delete("/v1/account", "del1", extra=":fresh")
    assert res.status_code == 200 and res.json()["status"] == "COMPLETED"
    docs = container.store.dump()
    assert "users/del1" not in docs
    assert f"public_profiles/{me['public_id']}" not in docs
    assert not [p for p in docs if p.startswith("blocks/")]
    reservation = docs["username_registry/leavingsoon"]
    assert reservation["state"] == "RESERVED" and reservation["reserved_for_uid"] is None
    assert container.auth_admin.deleted == ["del1"]
    # Name stays reserved from others for 30 days.
    api.post("/v1/onboarding/consent", "del3", {"age_gate_confirmed": True, "terms_version": TERMS_VERSION,
                                                 "privacy_version": PRIVACY_VERSION})
    assert api.post("/v1/profile/username", "del3", {"username": "LeavingSoon"}).json()["error"]["code"] == \
        "USERNAME_TAKEN"


def test_deletion_waits_for_active_match(api, container):
    api.onboard("dm1")
    container.store.run_transaction_sync(lambda t: t.set("user_runtime/dm1", {
        **idle_runtime("dm1", 0), "state": "MATCH_ACTIVE", "active_match_id": "m1"}))
    res = api.delete("/v1/account", "dm1", extra=":fresh")
    assert res.json()["status"] == "PENDING_MATCH"
    docs = container.store.dump()
    assert docs["users/dm1"]["status"] == "DELETION_PENDING"
    assert docs["user_runtime/dm1"]["state"] == "MATCH_ACTIVE"  # the live match is never orphaned
    assert container.auth_admin.deleted == []
    # Queue/match entry is refused while deletion is pending.
    assert api.get("/v1/profile", "dm1").json()["error"]["code"] == "ACCOUNT_DELETION_PENDING"
