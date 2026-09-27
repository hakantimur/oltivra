"""Friends, search, challenges, parties and rematch (spec §6, §40 social)."""

from __future__ import annotations

import pytest

from app.common.tasks import TaskKind
from tests.unit.test_matchmaking import (
    bot_fill_match,
    join,
    live_root,
    play_round_human_wins,
    public,
    run_tasks,
)


@pytest.fixture
def players(api):
    for uid in ("u1", "u2", "u3", "u4"):
        api.onboard(uid)
    return api


def pid(container, uid):
    return container.profiles.public_id(uid)


def befriend(players, container, a, b):
    players.post("/v1/friends/requests", a, {"target_public_id": pid(container, b)})
    request_id = players.get("/v1/friends", b).json()["incoming_requests"][0]["request_id"]
    res = players.post(f"/v1/friends/requests/{request_id}/accept", b)
    assert res.json()["state"] == "ACCEPTED"


def runtime(container, uid):
    return (container.store._docs.get(f"user_runtime/{uid}") or {"state": "IDLE"})["state"]


# ---------------------------------------------------------------------------------------------- friends


def test_search_prefix_exact_first_and_minimum_profile(players, container):
    res = players.get("/v1/users/search", "u1", username="user_u2").json()["results"]
    assert res[0]["public_id"] == pid(container, "u2") and res[0]["relationship"] == "NONE"
    assert set(res[0]) == {"public_id", "username", "avatar_id", "frame_id", "league", "level", "relationship"}
    prefix = players.get("/v1/users/search", "u1", username="user_").json()["results"]
    assert pid(container, "u1") not in {r["public_id"] for r in prefix}
    assert {pid(container, u) for u in ("u2", "u3", "u4")} <= {r["public_id"] for r in prefix}


def test_search_finds_bots_like_humans(players):
    results = players.get("/v1/users/search", "u1", username="ava_k").json()["results"]
    assert results and set(results[0]) == {"public_id", "username", "avatar_id", "frame_id", "league", "level",
                                           "relationship"}


def test_friend_request_flow_with_notification(players, container):
    players.post("/v1/devices", "u2", {"token": "fcm-token-u2-xxxxxxxx", "platform": "android"})
    res = players.post("/v1/friends/requests", "u1", {"target_public_id": pid(container, "u2")})
    assert res.json()["relationship"] == "REQUEST_SENT"
    again = players.post("/v1/friends/requests", "u1", {"target_public_id": pid(container, "u2")})
    assert again.json()["relationship"] == "REQUEST_SENT"
    assert len([k for k in container.store._docs if k.startswith("friend_requests/")]) == 1
    sent = container.notifications.sender.sent
    assert len(sent) == 1 and sent[0].kind == "FRIEND_REQUEST" and sent[0].data["public_id"] == pid(container, "u1")
    overview = players.get("/v1/friends", "u2").json()
    assert overview["incoming_requests"][0]["public_id"] == pid(container, "u1")
    request_id = overview["incoming_requests"][0]["request_id"]
    assert players.post(f"/v1/friends/requests/{request_id}/accept", "u1").status_code == 404  # sender cannot
    assert players.post(f"/v1/friends/requests/{request_id}/accept", "u2").json()["state"] == "ACCEPTED"
    assert players.get("/v1/friends", "u1").json()["friends"][0]["public_id"] == pid(container, "u2")
    search = players.get("/v1/users/search", "u1", username="user_u2").json()["results"]
    assert search[0]["relationship"] == "FRIEND"
    players.delete(f"/v1/friends/{pid(container, 'u2')}", "u1")
    assert players.get("/v1/friends", "u1").json()["friends"] == []


def test_mutual_requests_become_friends(players, container):
    players.post("/v1/friends/requests", "u1", {"target_public_id": pid(container, "u2")})
    res = players.post("/v1/friends/requests", "u2", {"target_public_id": pid(container, "u1")})
    assert res.json()["relationship"] == "FRIEND"


def test_blocks_suppress_requests_without_revealing(players, container):
    players.post(f"/v1/blocks/{pid(container, 'u1')}", "u2")
    res = players.post("/v1/friends/requests", "u1", {"target_public_id": pid(container, "u2")})
    assert res.status_code == 200 and res.json()["relationship"] == "REQUEST_SENT"
    assert players.get("/v1/friends", "u2").json()["incoming_requests"] == []
    mine = players.post("/v1/friends/requests", "u2", {"target_public_id": pid(container, "u1")})
    assert mine.status_code == 403 and mine.json()["error"]["code"] == "BLOCKED"
    # Blocked users disappear from search for the blocker.
    assert players.get("/v1/users/search", "u2", username="user_u1").json()["results"] == []


def test_existing_friendship_hidden_while_blocked(players, container):
    befriend(players, container, "u1", "u2")
    players.post(f"/v1/blocks/{pid(container, 'u2')}", "u1")
    assert players.get("/v1/friends", "u1").json()["friends"] == []
    assert players.get("/v1/friends", "u2").json()["friends"] == []
    assert any(k.startswith("friendships/") for k in container.store._docs)  # kept for audit


# ---------------------------------------------------------------------------------------------- challenges


def challenge(players, container, host="u1", friends=("u2", "u3")):
    for friend in friends:
        befriend(players, container, host, friend)
    res = players.post("/v1/challenges", host, {"friend_public_ids": [pid(container, f) for f in friends],
                                                "question_language": "en"})
    assert res.status_code == 200, res.text
    return res.json()


def invite_token(players, uid):
    return players.get("/v1/challenges/invites", uid).json()["invites"][0]["invite_token"]


def test_challenge_accept_start_fills_bots_unranked(players, container):
    party = challenge(players, container)
    assert party["state"] == "WAITING" and runtime(container, "u1") == "IN_PARTY"
    token = invite_token(players, "u2")
    wrong = players.post(f"/v1/challenges/{token}/accept", "u2", {"accept_question_language": "tr"})
    assert wrong.status_code == 400 and wrong.json()["error"]["detail"]["reason"] == "language_not_accepted"
    ok = players.post(f"/v1/challenges/{token}/accept", "u2", {"accept_question_language": "en"}).json()
    assert ok["state"] == "READY" and runtime(container, "u2") == "IN_PARTY"
    assert players.post(f"/v1/parties/{party['party_id']}/start", "u2").status_code == 403  # host only
    started = players.post(f"/v1/parties/{party['party_id']}/start", "u1").json()
    assert started["state"] == "MATCHED"
    match_id = started["match_id"]
    root = live_root(container, match_id)
    assert len(root["public"]["participants"]) == 4 and set(root["player_private"]) == {"u1", "u2"}
    assert root["authoritative"]["ranked"]["eligible"] is False
    assert container.store._docs[f"match_index/{match_id}"]["source"] == "CHALLENGE"
    assert runtime(container, "u1") == runtime(container, "u2") == "MATCH_ACTIVE"
    late = players.post(f"/v1/challenges/{invite_token_raw(container, 'u3')}/accept", "u3",
                        {"accept_question_language": "en"})
    assert late.status_code == 409 and late.json()["error"]["code"] == "PARTY_EXPIRED"


def invite_token_raw(container, uid):
    return next(p.split("/")[1] for p, d in container.store._docs.items()
                if p.startswith("party_invites/") and d["uid"] == uid)


def test_challenge_requires_friendship(players, container):
    res = players.post("/v1/challenges", "u1", {"friend_public_ids": [pid(container, "u2")],
                                                "question_language": "en"})
    assert res.status_code == 403


def test_party_auto_starts_at_expiry_with_two_humans(players, container):
    party = challenge(players, container)
    players.post(f"/v1/challenges/{invite_token(players, 'u2')}/accept", "u2", {"accept_question_language": "en"})
    container.clock.set(party["expires_at_ms"])
    run_tasks(container)
    doc = container.store._docs[f"parties/{party['party_id']}"]
    assert doc["state"] == "MATCHED" and runtime(container, "u2") == "MATCH_ACTIVE"


def test_party_expires_without_enough_humans(players, container):
    party = challenge(players, container)
    container.clock.set(party["expires_at_ms"])
    run_tasks(container)
    assert container.store._docs[f"parties/{party['party_id']}"]["state"] == "EXPIRED"
    assert runtime(container, "u1") == "IDLE"


def test_member_leave_and_host_leave(players, container):
    party = challenge(players, container)
    for friend in ("u2", "u3"):
        players.post(f"/v1/challenges/{invite_token(players, friend)}/accept", friend,
                     {"accept_question_language": "en"})
    left = players.post(f"/v1/parties/{party['party_id']}/leave", "u2").json()
    assert left["state"] == "READY" and runtime(container, "u2") == "IDLE"
    host = players.post(f"/v1/parties/{party['party_id']}/leave", "u1").json()
    assert host["state"] == "CANCELLED" and runtime(container, "u1") == "IDLE" and runtime(container, "u3") == "IDLE"


def test_party_cancels_when_fewer_than_two_humans_remain(players, container):
    party = challenge(players, container)
    players.post(f"/v1/challenges/{invite_token(players, 'u2')}/accept", "u2", {"accept_question_language": "en"})
    left = players.post(f"/v1/parties/{party['party_id']}/leave", "u2").json()
    assert left["state"] == "CANCELLED"
    doc = container.store._docs[f"parties/{party['party_id']}"]
    assert doc["cancel_reason"] == "INSUFFICIENT_HUMANS"
    assert runtime(container, "u1") == "IDLE" and runtime(container, "u2") == "IDLE"


def test_one_activity_at_a_time(players, container):
    challenge(players, container)
    res = join(players, "u1")
    assert res.status_code == 409 and res.json()["error"]["code"] == "ACTIVE_RUNTIME_CONFLICT"
    join(players, "u2")  # queued player cannot accept a challenge
    res = players.post(f"/v1/challenges/{invite_token(players, 'u2')}/accept", "u2",
                       {"accept_question_language": "en"})
    assert res.status_code == 409


def test_blocked_invitee_cannot_join(players, container):
    befriend(players, container, "u2", "u3")
    party = challenge(players, container)
    players.post(f"/v1/challenges/{invite_token(players, 'u2')}/accept", "u2", {"accept_question_language": "en"})
    players.post(f"/v1/blocks/{pid(container, 'u2')}", "u3")
    res = players.post(f"/v1/challenges/{invite_token(players, 'u3')}/accept", "u3",
                       {"accept_question_language": "en"})
    assert res.status_code == 403 and res.json()["error"]["code"] == "BLOCKED"
    assert container.store._docs[f"parties/{party['party_id']}"]["accepted_uids"] == ["u1", "u2"]


# ---------------------------------------------------------------------------------------------- rematch


def finish_bot_match(players, container, uid="u1"):
    match_id = bot_fill_match(players, container, uid)
    for _ in range(10):
        play_round_human_wins(players, container, match_id, uid=uid)
    return match_id


def test_rematch_after_settlement_uses_fresh_questions(players, container):
    prior = finish_bot_match(players, container)
    pub = public(container, prior)
    assert pub["settlement_status"] == "SETTLED" and pub["rematch_until_ms"] > container.clock.now_ms()
    res = players.post(f"/v1/matches/{prior}/rematch", "u1").json()
    assert res["kind"] == "REMATCH" and res["state"] == "MATCHED"  # sole human accepted: starts at once
    new_match = res["match_id"]
    assert new_match != prior and runtime(container, "u1") == "MATCH_ACTIVE"
    prior_gids = {r["gid"] for r in container.store._docs[f"match_history/{prior}"]["round_log"]}
    new_plan = live_root(container, new_match)["authoritative"]["plan"]
    new_gids = {i["gid"] for i in new_plan["normal"]}
    assert not prior_gids & new_gids


def test_rematch_requires_settlement_and_window(players, container):
    match_id = bot_fill_match(players, container)
    res = players.post(f"/v1/matches/{match_id}/rematch", "u1")
    assert res.status_code == 409 and res.json()["error"]["code"] == "MATCH_SETTLEMENT_PENDING"
    for _ in range(10):
        play_round_human_wins(players, container, match_id)
    container.clock.advance(10_001)
    late = players.post(f"/v1/matches/{match_id}/rematch", "u1")
    assert late.status_code == 409 and late.json()["error"]["code"] == "PARTY_EXPIRED"
    assert players.post(f"/v1/matches/{match_id}/rematch", "u2").status_code == 403


def test_partial_rematch_starts_at_window_end(players, container):
    for uid in ("u1", "u2", "u3", "u4"):
        res = join(players, uid)
    prior = res.json()["match"]["match_id"]
    for _ in range(10):
        play_round_human_wins(players, container, prior, uid="u1")
    first = players.post(f"/v1/matches/{prior}/rematch", "u1").json()
    assert first["state"] == "READY"
    second = players.post(f"/v1/rematches/{first['party_id']}/accept", "u2").json()
    assert {m["public_id"] for m in second["members"] if m["status"] == "ACCEPTED"} == {pid(container, "u1"),
                                                                                         pid(container, "u2")}
    expiry = [t for t in container.tasks.pending(TaskKind.REMATCH_EXPIRY)][0]
    container.clock.set(expiry.eta_ms)
    run_tasks(container)
    party = container.store._docs[f"parties/{first['party_id']}"]
    assert party["state"] == "MATCHED"
    root = live_root(container, party["match_id"])
    assert set(root["player_private"]) == {"u1", "u2"} and len(root["public"]["participants"]) == 4
    assert root["authoritative"]["ranked"]["eligible"] is False  # 2 humans < ranked minimum
    assert runtime(container, "u3") == "IDLE"


# ---------------------------------------------------------------------------------------------- public profile


def test_public_profile_with_relationship_and_blocks(players, container):
    target = pid(container, "u2")
    res = players.get(f"/v1/users/{target}", "u1")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["profile"]["public_id"] == target and body["profile"]["username_display"]
    assert set(body["profile"]) == {"public_id", "username_display", "avatar_id", "frame_id", "featured_badge_ids",
                                    "league", "level", "quick_best_ranked_win_streak",
                                    "survival_ranked_crowns_lifetime", "quick_ranked_wins_lifetime"}
    assert body["relationship"] == {"friend": False, "outgoing_request": False, "incoming_request": False,
                                    "blocked": False}
    players.post("/v1/friends/requests", "u1", {"target_public_id": target})
    assert players.get(f"/v1/users/{target}", "u1").json()["relationship"]["outgoing_request"] is True
    assert players.get(f"/v1/users/{pid(container, 'u1')}", "u2").json()["relationship"]["incoming_request"] is True
    request_id = players.get("/v1/friends", "u2").json()["incoming_requests"][0]["request_id"]
    players.post(f"/v1/friends/requests/{request_id}/accept", "u2")
    assert players.get(f"/v1/users/{target}", "u1").json()["relationship"]["friend"] is True
    # The blocker still sees the profile, flagged; the blocked viewer cannot tell it from an unknown ID.
    players.post(f"/v1/blocks/{target}", "u1")
    mine = players.get(f"/v1/users/{target}", "u1").json()
    assert mine["relationship"] == {"friend": False, "outgoing_request": False, "incoming_request": False,
                                    "blocked": True}
    hidden = players.get(f"/v1/users/{pid(container, 'u1')}", "u2")
    assert hidden.status_code == 404 and hidden.json()["error"]["code"] == "NOT_FOUND"
    assert players.get("/v1/users/pdoesnotexist000000000", "u1").status_code == 404
