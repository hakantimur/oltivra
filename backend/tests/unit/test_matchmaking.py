"""Phase 3 exit criteria: durable tickets, atomic roster claim, canonical live root, resolver, settlement."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from app.common.tasks import TaskKind
from app.matches.factory import HumanSeat
from app.matches.model import Mode
from app.matches.service import root_path
from app.matches.shards import shard_for


def join(api, uid: str, mode: str = "quick", rtt: int = 40):
    return api.post(f"/v1/matchmaking/{mode}/join", uid, {"median_rtt_ms": rtt})


def run_tasks(container, now: int | None = None) -> int:
    return asyncio.run(container.tasks.run_due(now if now is not None else container.clock.now_ms()))


def live_root(container, match_id: str) -> dict[str, Any]:
    idx = container.store._docs[f"match_index/{match_id}"]
    return container.live.dump(idx["rtdb_shard_id"]).get("matches", {}).get(match_id) or {}


def runtime(container, uid: str) -> dict[str, Any]:
    return container.store._docs.get(f"user_runtime/{uid}") or {"state": "IDLE"}


@pytest.fixture
def players(api):
    for uid in ("u1", "u2", "u3", "u4", "u5"):
        api.onboard(uid)
    return api


def bot_fill_match(api, container, uid: str = "u1") -> str:
    res = join(api, uid)
    assert res.status_code == 200, res.text
    assert res.json()["state"] == "QUEUED"
    container.clock.set(res.json()["human_fill_at_ms"])
    status = api.get("/v1/matchmaking/status", uid).json()
    assert status["state"] == "MATCHED", status
    return status["match"]["match_id"]


# ---------------------------------------------------------------------------------------------- tickets


def test_join_queues_then_bot_fill_at_deadline(players, container):
    res = join(players, "u1")
    body = res.json()
    assert body["state"] == "QUEUED" and body["latency_band"] == "0_60"
    assert body["human_fill_at_ms"] == container.clock.now_ms() + 3000
    assert runtime(container, "u1")["state"] == "QUEUED"
    # Before the fill deadline nothing forms.
    container.clock.advance(1000)
    assert players.get("/v1/matchmaking/status", "u1").json()["state"] == "QUEUED"
    container.clock.advance(2000)
    status = players.get("/v1/matchmaking/status", "u1").json()
    assert status["state"] == "MATCHED"
    match_id = status["match"]["match_id"]
    assert status["match"]["rtdb_shard_id"] == shard_for(container.keys, match_id, container.settings.shard_ids)
    assert runtime(container, "u1")["state"] == "MATCH_ACTIVE"
    root = live_root(container, match_id)
    assert set(root) >= {"authoritative", "public", "player_private", "access"}
    assert len(root["public"]["participants"]) == 4
    assert root["authoritative"]["ranked"]["eligible"] is False
    assert root["access"] == {"u1": "participant"}


def test_public_projection_never_distinguishes_bots(players, container):
    match_id = bot_fill_match(players, container)
    public = live_root(container, match_id)["public"]
    for p in public["participants"].values():
        assert "is_bot" not in p and "kind" not in p and "bot_id" not in p
        assert p["display_name"] and p["avatar_id"]
    text = str(public)
    assert "bot_" not in text and "correct" not in text.replace("correct_answer_reveal", "")
    # Every roster pid (including bots) resolves to a public profile of the same shape (D3).
    shapes = {tuple(sorted(container.store._docs[f"public_profiles/{pid}"])) for pid in public["participants"]}
    assert len(shapes) == 1
    # Blocking a bot behaves exactly like blocking a human.
    for pid in public["participants"]:
        if pid != container.profiles.public_id("u1"):
            assert players.post(f"/v1/blocks/{pid}", "u1").status_code == 200


def test_four_compatible_humans_form_immediately(players, container):
    for uid in ("u1", "u2", "u3"):
        assert join(players, uid).json()["state"] == "QUEUED"
    res = join(players, "u4")
    assert res.json()["state"] == "MATCHED"
    match_id = res.json()["match"]["match_id"]
    for uid in ("u1", "u2", "u3", "u4"):
        assert runtime(container, uid)["active_match_id"] == match_id
    root = live_root(container, match_id)
    assert root["authoritative"]["ranked"]["eligible"] is True
    assert set(root["player_private"]) == {"u1", "u2", "u3", "u4"}
    idx = container.store._docs[f"match_index/{match_id}"]
    assert sorted(idx["participant_uids"]) == ["u1", "u2", "u3", "u4"]
    # The others learn about the match on their next status poll.
    assert players.get("/v1/matchmaking/status", "u1").json()["match"]["match_id"] == match_id


def test_duplicate_join_returns_same_ticket_and_second_queue_conflicts(players, container):
    first = join(players, "u1").json()
    again = join(players, "u1").json()
    assert again["ticket_id"] == first["ticket_id"]
    res = join(players, "u1", mode="survival")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "ACTIVE_RUNTIME_CONFLICT"


def test_idempotent_join_replays_same_response(players):
    key = str(uuid.uuid4())
    a = players.post("/v1/matchmaking/quick/join", "u1", {"median_rtt_ms": 40}, key=key).json()
    b = players.post("/v1/matchmaking/quick/join", "u1", {"median_rtt_ms": 40}, key=key).json()
    assert a == b


def test_leave_cancels_queued_ticket_idempotently(players, container):
    ticket = join(players, "u1").json()["ticket_id"]
    res = players.delete("/v1/matchmaking/quick/leave", "u1")
    assert res.json()["state"] == "CANCELLED"
    assert container.store._docs[f"matchmaking_tickets/{ticket}"]["state"] == "CANCELLED"
    assert runtime(container, "u1")["state"] == "IDLE"
    assert players.delete("/v1/matchmaking/quick/leave", "u1").json()["state"] == "IDLE"
    # Can queue again afterwards.
    assert join(players, "u1").json()["state"] == "QUEUED"


def test_leave_after_match_returns_match_pointer(players, container):
    match_id = bot_fill_match(players, container)
    res = players.delete("/v1/matchmaking/quick/leave", "u1").json()
    assert res["state"] == "MATCHED" and res["match"]["match_id"] == match_id


def test_ticket_expires_without_silent_bot_match(players, container):
    ticket = join(players, "u1").json()
    container.clock.set(ticket["expires_at_ms"])
    status = players.get("/v1/matchmaking/status", "u1").json()
    assert status["state"] == "EXPIRED"
    assert runtime(container, "u1")["state"] == "IDLE"
    assert not any(k.startswith("match_index/") for k in container.store._docs)


def test_never_widen_across_latency_band(players, container):
    join(players, "u1", rtt=30)
    join(players, "u2", rtt=150)
    container.clock.advance(3000)
    a = players.get("/v1/matchmaking/status", "u1").json()["match"]["match_id"]
    b = players.get("/v1/matchmaking/status", "u2").json()["match"]["match_id"]
    assert a != b


def test_blocked_pair_is_not_matched(players, container):
    pid_u2 = container.profiles.public_id("u2")
    assert players.post(f"/v1/blocks/{pid_u2}", "u1").status_code == 200
    join(players, "u1")
    join(players, "u2")
    container.clock.advance(3000)
    a = players.get("/v1/matchmaking/status", "u1").json()["match"]["match_id"]
    b = players.get("/v1/matchmaking/status", "u2").json()["match"]["match_id"]
    assert a != b


def test_mmr_widening_after_wait(players, container):
    container.store._docs["users/u2"]["mmr"] = 1200  # outside the initial ±100, inside widened ±250
    join(players, "u1")
    join(players, "u2")
    ticket = container.store._docs[f"matchmaking_tickets/{runtime(container, 'u1')['active_ticket_id']}"]
    config = asyncio.run(container.config.get())
    early = asyncio.run(container.matchmaking.select_roster(ticket, config, set()))
    assert [t["uid"] for t in early] == ["u1"]
    container.clock.advance(1500)
    late = asyncio.run(container.matchmaking.select_roster(ticket, config, set()))
    assert [t["uid"] for t in late] == ["u1", "u2"]


def test_concurrent_claims_never_double_match(players, container):
    """Two instances building overlapping rosters: only one claim commits (Phase 3 exit)."""
    join(players, "u1")
    join(players, "u2")
    join(players, "u3")
    tickets = {uid: container.store._docs[f"matchmaking_tickets/{runtime(container, uid)['active_ticket_id']}"]
               for uid in ("u1", "u2", "u3")}

    def seats(*uids):
        return [HumanSeat(uid=u, username=tickets[u]["username"], avatar_id=tickets[u]["avatar_id"],
                          frame_id="frame_none", mmr=1000, ticket_id=tickets[u]["ticket_id"]) for u in uids]

    async def race():
        first = await container.match_factory.prepare(mode=Mode.QUICK, language="en", humans=seats("u1", "u2"))
        second = await container.match_factory.prepare(mode=Mode.QUICK, language="en", humans=seats("u2", "u3"))
        return await asyncio.gather(container.matchmaking.claim(first), container.matchmaking.claim(second))

    results = asyncio.run(race())
    assert sorted(map(sorted, results)) == [[], ["u2"]]  # the overlapping player fails the second claim
    matched = [k for k in container.store._docs if k.startswith("match_index/")]
    assert len(matched) == 1
    assert runtime(container, "u2")["state"] == "MATCH_ACTIVE"
    assert runtime(container, "u3")["state"] == "QUEUED"


def test_capacity_refusal_is_retryable_and_ticket_still_expires(players, container):
    for sid in container.settings.shard_ids:
        container.store._docs[f"shard_health/{sid}"] = {"shard_id": sid, "active_rooms": 10_000}
    ticket = join(players, "u1").json()
    container.clock.set(ticket["human_fill_at_ms"])
    status = players.get("/v1/matchmaking/status", "u1").json()
    assert status["state"] == "QUEUED" and status["capacity_limited"] is True
    container.clock.set(ticket["expires_at_ms"])
    assert players.get("/v1/matchmaking/status", "u1").json()["state"] == "EXPIRED"


# ---------------------------------------------------------------------------------------------- live match


def private(container, match_id: str, uid: str) -> dict[str, Any]:
    return live_root(container, match_id)["player_private"][uid]


def public(container, match_id: str) -> dict[str, Any]:
    return live_root(container, match_id)["public"]


def answer(api, container, match_id: str, uid: str, correct: bool = True, request_id: str | None = None):
    auth = live_root(container, match_id)["authoritative"]
    rnd = auth["round"]
    order = private(container, match_id, uid)["option_order"]
    concept = rnd["correct"] if correct else next(c for c in order.values() if c != rnd["correct"])
    body = {"round_id": rnd["round_id"], "option_id": concept}
    return api.post(f"/v1/matches/{match_id}/answer", uid, body, key=request_id)


def play_round_human_wins(api, container, match_id: str, uid: str = "u1") -> None:
    pub = public(container, match_id)
    assert pub["state"] == "ROUND_LOADING", pub["state"]
    container.clock.set(pub["starts_at_ms"])
    run_tasks(container)
    container.clock.advance(500)  # faster than any bot (min response 1.3s)
    res = answer(api, container, match_id, uid)
    assert res.status_code == 200, res.text
    assert res.json()["correct"] is True and res.json()["score_delta"] == 10
    pub = public(container, match_id)
    assert pub["state"] == "ROUND_REVEAL"
    container.clock.set(pub["reveal_ends_at_ms"] + 50)
    run_tasks(container)


def run_until_finished(container, match_id: str) -> None:
    for _ in range(200):
        pub = public(container, match_id)
        if pub.get("state") in ("FINISHED", "CANCELLED"):
            return
        pending = sorted(t.eta_ms for t in container.tasks.pending() if t.kind != TaskKind.CLEANUP)
        container.clock.set(max(container.clock.now_ms(), pending[0]))
        run_tasks(container)
    raise AssertionError("match did not finish")


def test_full_quick_match_settles_and_cleans_up(players, container):
    match_id = bot_fill_match(players, container)
    for _ in range(10):
        play_round_human_wins(players, container, match_id)
    root = live_root(container, match_id)
    assert root["public"]["state"] == "FINISHED"
    assert root["public"]["result_summary"]["standings"][0]["score"] == 100
    assert root["player_private"]["u1"]["settlement"]["place"] == 1
    assert runtime(container, "u1")["state"] == "IDLE"
    ledger = container.store._docs[f"settlement_ledgers/{match_id}"]
    assert ledger["status"] == "SETTLED"
    history = container.store._docs[f"match_history/{match_id}"]
    assert history["participant_uids"] == ["u1"] and len(history["question_versions"]) == 10
    assert history["ranked_eligible"] is False and history["bot_slot_count"] == 3
    assert len(container.store._docs["user_recent_questions/u1"]["qids"]) == 10
    assert container.store._docs[f"match_index/{match_id}"]["state"] == "FINISHED"
    # Settlement replay is harmless.
    assert asyncio.run(container.settlement.run(match_id, history_shard(container, match_id)))["replay"] is True
    cleanup = container.tasks.pending(TaskKind.CLEANUP)
    assert len(cleanup) == 1
    container.clock.set(cleanup[0].eta_ms)
    run_tasks(container)
    assert live_root(container, match_id) == {}
    # The player can queue again.
    assert join(players, "u1").json()["state"] == "QUEUED"


def history_shard(container, match_id: str) -> str:
    return container.store._docs[f"match_index/{match_id}"]["rtdb_shard_id"]


def test_answer_validation_and_replay(players, container):
    match_id = bot_fill_match(players, container)
    pub = public(container, match_id)
    # Before the round starts the answer is rejected.
    early = answer(players, container, match_id, "u1")
    assert early.status_code == 409 and early.json()["error"]["code"] == "ROUND_NOT_ACTIVE"
    container.clock.set(pub["starts_at_ms"] + 100)
    key = str(uuid.uuid4())
    wrong = answer(players, container, match_id, "u1", correct=False, request_id=key)
    assert wrong.status_code == 200 and wrong.json()["correct"] is False and wrong.json()["score_delta"] == -4
    replay = answer(players, container, match_id, "u1", correct=False, request_id=key)
    assert replay.json()["replay"] is True and replay.json()["score_delta"] == -4
    second = answer(players, container, match_id, "u1", correct=True)
    assert second.status_code == 409 and second.json()["error"]["code"] == "ANSWER_ALREADY_SUBMITTED"
    assert private(container, match_id, "u1")["own_answer_status"] == "ANSWERED_WRONG"
    rnd = live_root(container, match_id)["authoritative"]["round"]
    bogus = players.post(f"/v1/matches/{match_id}/answer", "u1", {"round_id": rnd["round_id"],
                                                                  "option_id": "nope"})
    assert bogus.status_code in (400, 409)


def test_outsider_cannot_answer_or_view(players, container):
    match_id = bot_fill_match(players, container)
    res = players.get(f"/v1/matches/{match_id}", "u2")
    assert res.status_code == 403
    rnd = live_root(container, match_id)["authoritative"]["round"]
    res = players.post(f"/v1/matches/{match_id}/answer", "u2", {"round_id": rnd["round_id"], "option_id": "x"})
    assert res.status_code == 403 and res.json()["error"]["code"] == "NOT_MATCH_PARTICIPANT"


def test_view_returns_safe_projections(players, container):
    match_id = bot_fill_match(players, container)
    view = players.get(f"/v1/matches/{match_id}", "u1").json()
    assert view["role"] == "participant" and view["public"]["match_id"] == match_id
    assert set(view["player_private"]["option_order"]) == {"A", "B", "C", "D"}
    assert "authoritative" not in view and "rtdb_url" in view


def test_sync_resolves_when_tasks_are_lost(players, container):
    match_id = bot_fill_match(players, container)
    pub = public(container, match_id)
    container.clock.set(pub["starts_at_ms"] + 10)
    res = players.post(f"/v1/matches/{match_id}/sync", "u1")
    assert res.status_code == 200 and res.json()["state"] == "ROUND_ACTIVE"
    # Round expires without answers: a later sync closes it even though no task ran.
    container.clock.set(pub["ends_at_ms"] + 400)
    assert players.post(f"/v1/matches/{match_id}/sync", "u1").json()["state"] in ("ROUND_REVEAL",)


def test_duplicate_and_late_tasks_are_harmless(players, container):
    bot_fill_match(players, container)
    start = container.tasks.pending(TaskKind.ROUND_START)[0]
    body = start.body()
    from app.tasks.dispatch import dispatch_task

    container.clock.set(start.eta_ms)
    first = asyncio.run(dispatch_task(container, body))
    again = asyncio.run(dispatch_task(container, body))
    assert first["changed"] is True and again["changed"] is False
    # A task for a cleaned-up match is a no-op.
    gone = {**body, "match_id": "missing"}
    assert asyncio.run(dispatch_task(container, gone))["changed"] is False


def test_leave_mid_match_then_all_humans_left_finishes(players, container):
    match_id = bot_fill_match(players, container)
    pub = public(container, match_id)
    container.clock.set(pub["starts_at_ms"] + 100)
    res = players.post(f"/v1/matches/{match_id}/leave", "u1")
    assert res.status_code == 200 and res.json()["left"] is True
    run_tasks(container)
    root = live_root(container, match_id)
    assert root["public"]["state"] == "FINISHED"
    assert root["public"]["participants"][container.profiles.public_id("u1")]["left"] is True
    assert runtime(container, "u1")["state"] == "IDLE"
    assert container.store._docs[f"settlement_ledgers/{match_id}"]["status"] == "SETTLED"


def test_leave_one_of_many_keeps_match_running(players, container):
    for uid in ("u1", "u2", "u3", "u4"):
        res = join(players, uid)
    match_id = res.json()["match"]["match_id"]
    assert players.post(f"/v1/matches/{match_id}/leave", "u2").status_code == 200
    assert runtime(container, "u2")["state"] == "SETTLEMENT_PENDING"
    assert public(container, match_id)["state"] in ("ROUND_LOADING", "ROUND_ACTIVE")
    # A settlement-pending player cannot queue.
    res = join(players, "u2")
    assert res.status_code == 409 and res.json()["error"]["code"] == "MATCH_SETTLEMENT_PENDING"


def test_client_config_lists_shards(players):
    config = players.get("/v1/client-config", "u1").json()
    assert set(config["rtdb_shards"]) == {"live-00", "live-01", "live-02", "live-03"}


def test_bootstrap_reports_active_match_pointer(players, container):
    match_id = bot_fill_match(players, container)
    boot = players.post("/v1/session/bootstrap", "u1", {}).json()
    assert boot["runtime"]["match_id"] == match_id and boot["runtime"]["state"] == "MATCH_ACTIVE"
    assert boot["runtime"]["shard_id"] == history_shard(container, match_id)


def test_deletion_requested_mid_match_completes_after_settlement(players, container):
    match_id = bot_fill_match(players, container)
    res = players.delete("/v1/account", "u1", extra=":fresh")
    assert res.status_code == 200 and res.json()["status"] == "PENDING_MATCH"
    # The deleting player can no longer act; the match plays out on server events alone.
    run_until_finished(container, match_id)
    assert container.store._docs["deletion_requests/u1"]["status"] == "COMPLETED"


def test_live_root_key_is_match_scoped(players, container):
    match_id = bot_fill_match(players, container)
    assert root_path(match_id) == f"matches/{match_id}"


# ---------------------------------------------------------------------------------------------- survival


def test_survival_bot_fill_plays_to_single_winner_and_settles(players, container):
    res = join(players, "u1", mode="survival")
    ticket = res.json()
    assert ticket["human_fill_at_ms"] == container.clock.now_ms() + 5000
    container.clock.set(ticket["human_fill_at_ms"])
    status = players.get("/v1/matchmaking/status", "u1").json()
    match_id = status["match"]["match_id"]
    root = live_root(container, match_id)
    assert len(root["public"]["participants"]) == 10
    assert root["public"]["mode"] == "SURVIVAL" and root["public"]["active_count"] == 10
    run_until_finished(container, match_id)
    root = live_root(container, match_id)
    standings = root["public"]["result_summary"]["standings"]
    assert [s["place"] for s in standings].count(1) == 1
    assert root["public"]["result_summary"]["winner_pid"] == standings[0]["pid"]
    assert runtime(container, "u1")["state"] == "IDLE"
    assert container.store._docs[f"settlement_ledgers/{match_id}"]["status"] == "SETTLED"


def test_survival_refill_effect_extends_pool(players, container):
    res = join(players, "u1", mode="survival")
    container.clock.set(res.json()["human_fill_at_ms"])
    match_id = players.get("/v1/matchmaking/status", "u1").json()["match"]["match_id"]
    shard = history_shard(container, match_id)
    from app.survival import rules

    before = rules.pool_remaining(live_root(container, match_id)["authoritative"])
    asyncio.run(container.survival_refill.refill(match_id, shard, {"batch": 1}))
    auth = live_root(container, match_id)["authoritative"]
    assert rules.pool_remaining(auth) > before
    assert auth["refill_batches"] == 1
    used = set(auth["used_gids"])
    pooled = [i["gid"] for items in auth["plan"]["pools"].values() for i in items]
    assert len(pooled) == len(set(pooled)) and not used & set(pooled)
