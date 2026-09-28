"""Settlement progression, missions, leaderboard, reactions and question reports (spec §5, §7, §11.3, §33)."""

from __future__ import annotations

import asyncio

import pytest

from app.common.clock import iso_week_id
from app.missions.service import apply_metrics, generate, period_ids
from app.moderation.question_reports import QuestionReportReason
from app.progression.service import question_stat_intents
from app.progression.xp import completed_survival_rounds, quick_base_xp, survival_base_xp
from app.questions.stats import FIELDS
from app.ranking.elo import Seat, rating_deltas
from tests.unit.test_matchmaking import (
    bot_fill_match,
    join,
    live_root,
    play_round_human_wins,
    private,
    public,
    run_tasks,
    run_until_finished,
)

# ---------------------------------------------------------------------------------------------- pure rules


def test_elo_pairwise_average_and_provisional_multiplier():
    seats = [Seat("a", 1000, 1), Seat("b", 1000, 2)]
    assert rating_deltas(seats, 32) == {"a": 16, "b": -16}
    assert rating_deltas(seats, 32, {"a": True}) == {"a": 24, "b": -16}
    tied = [Seat("a", 1000, 1), Seat("b", 1000, 1)]
    assert rating_deltas(tied, 40) == {"a": 0, "b": 0}
    with_bot = [Seat("a", 1000, 2), Seat("bot", 1450, 1, is_bot=True)]
    deltas = rating_deltas(with_bot, 32)
    assert set(deltas) == {"a"} and deltas["a"] == round(32 * (0 - 1 / (1 + 10 ** (450 / 400))))


def test_base_xp_formulas():
    assert quick_base_xp(100, 1, False) == 150
    assert quick_base_xp(-12, 4, False) == 20
    assert quick_base_xp(30, 1, True) == 40  # abandonment keeps participation + score, no placement bonus
    assert survival_base_xp(3, 1, False) == 10 + 24 + 60
    assert survival_base_xp(0, 10, False) == 12


def test_zero_answer_rescue_rounds_do_not_count_for_survival_xp():
    log = [
        {"eligible": ["p1", "p2"], "answers": {"p1": {"c": True, "ms": 1}}, "resolution": "NORMAL",
         "eliminated": ["p2"]},
        {"eligible": ["p1", "p3"], "answers": {}, "resolution": "NO_ANSWERS"},
        {"eligible": ["p1", "p3"], "answers": {"p1": {"c": False, "ms": 1}}, "resolution": "ALL_WRONG"},
        {"eligible": ["p1", "p3"], "answers": {"p1": {"c": True, "ms": 1}}, "resolution": "TIEBREAK_WINNER",
         "eliminated": ["p3"]},
    ]
    assert completed_survival_rounds(log, "p1") == 3
    assert completed_survival_rounds(log, "p2") == 0


def test_missions_are_deterministic_and_progress_caps():
    from app.common.server_config import GameConfig
    from tests.engine_helpers import KEYS

    config = GameConfig()
    now = 1_800_000_000_000
    ids = period_ids(now)
    a = generate(KEYS, "u1", "DAILY", ids["DAILY"], now, config)
    b = generate(KEYS, "u1", "DAILY", ids["DAILY"], now, config)
    assert a == b and len(a["missions"]) == 3
    weekly = generate(KEYS, "u1", "WEEKLY", ids["WEEKLY"], now, config)
    assert len(weekly["missions"]) == 4 and weekly["missions"][0]["xp"] == 100
    mission = a["missions"][0]
    done = apply_metrics(a, {mission["metric"]: 10_000}, now)
    assert mission["mission_id"] in done and a["missions"][0]["progress"] == mission["target"]
    assert apply_metrics(a, {mission["metric"]: 5}, now) == []  # completed missions never re-complete


def test_question_stat_intents_are_human_only_and_censor_quick_losers():
    state = {"mode": "QUICK", "participants": {"h1": {"kind": "HUMAN", "uid": "u1"}, "h2": {"kind": "HUMAN",
                                                                                              "uid": "u2"},
                                               "b1": {"kind": "BOT", "bot_id": "x"}},
             "round_log": [{"gid": "g1", "v": 2, "eligible": ["h1", "h2", "b1"], "winner": "b1",
                            "answers": {"b1": {"c": True, "ms": 2000}, "h1": {"c": False, "ms": 900}}}]}
    [intent] = question_stat_intents(state)
    assert intent["counts"] == {"shown": 2, "attempted": 1, "correct": 0, "wrong": 1, "no_answer": 0,
                                "censored_by_early_quick_winner": 1, "sum_response_ms": 900}
    assert set(intent["counts"]) <= set(FIELDS)


# ---------------------------------------------------------------------------------------------- settlement


@pytest.fixture
def players(api):
    for uid in ("u1", "u2", "u3", "u4"):
        api.onboard(uid)
    return api


def user(container, uid):
    return container.store._docs[f"users/{uid}"]


def test_unranked_bot_match_awards_xp_but_never_ranked_progress(players, container):
    match_id = bot_fill_match(players, container)
    for _ in range(10):
        play_round_human_wins(players, container, match_id)
    u = user(container, "u1")
    assert u["total_xp"] == 200 and u["matches_completed"] == 1 and u["quick_wins_lifetime"] == 1
    assert u["mmr"] == 1000 and u["ranked_matches_completed"] == 0
    assert u["quick_current_ranked_win_streak"] == 0 and u.get("quick_ranked_wins_lifetime", 0) == 0
    assert "badge_first_quick_win" in u["badge_ids"]
    # The win moves the hidden adaptive bot level up one win step (app.bots.difficulty).
    assert u["bot_level"] == 1.75 and u["bot_loss_streak"] == 0
    week = iso_week_id(container.clock.now_ms())
    assert f"weekly_user_stats/{week}_u1" not in container.store._docs
    settlement = private(container, match_id, "u1")["settlement"]
    assert settlement["xp_awarded"] == 200 and settlement["progress_level_after"] >= 2
    assert settlement["progress_ranked"] is False and "mmr_delta" not in settlement
    assert settlement["progress_new_badges"] == ["badge_first_quick_win"]
    profile = container.store._docs[f"public_profiles/{u['public_id']}"]
    assert profile["level"] == settlement["progress_level_after"]
    # Rewarded bonus XP is off by default: XP comes only from play (playtest 2026-09-27).
    assert f"reward_offers/{match_id}_u1" not in container.store._docs
    assert settlement["progress_reward_offer"] is False
    daily = players.get("/v1/missions/daily", "u1").json()
    assert any(m["progress"] > 0 for m in daily["missions"]) or all(
        m["template_id"] in ("play_survival_1", "win_ranked_quick_1", "send_reactions_5") for m in daily["missions"])
    # Human-only question statistics landed in sharded counters.
    stats = container.store.dump("question_stats_shards/")
    assert sum(int(d.get("shown", 0)) for d in stats.values()) == 10
    assert sum(int(d.get("correct", 0)) for d in stats.values()) == 10
    history = players.get("/v1/match-history", "u1").json()["matches"]
    assert history[0]["match_id"] == match_id and history[0]["place"] == 1 and "is_bot" not in str(history)
    cats = {c["category_id"]: c for c in players.get("/v1/category-stats", "u1").json()["categories"]}
    assert sum(c["correct"] for c in cats.values()) == 10


def ranked_match(players, container) -> str:
    for uid in ("u1", "u2", "u3", "u4"):
        res = join(players, uid)
    assert res.json()["state"] == "MATCHED"
    return res.json()["match"]["match_id"]


def test_ranked_match_updates_mmr_streak_weekly_and_leaderboard(players, container):
    match_id = ranked_match(players, container)
    assert live_root(container, match_id)["authoritative"]["ranked"]["eligible"] is True
    for _ in range(10):
        play_round_human_wins(players, container, match_id, uid="u1")
    u1 = user(container, "u1")
    # Four equal 1000 players, provisional K = 48: 48 * (3 - 1.5) / 3 = 24.
    assert u1["mmr"] == 1024 and u1["ranked_matches_completed"] == 1
    assert u1["quick_current_ranked_win_streak"] == 1 and u1["quick_ranked_wins_lifetime"] == 1
    losers = [user(container, u)["mmr"] - 1000 for u in ("u2", "u3", "u4")]
    # Unique tiebroken placements (spec §3.7): 2nd gains vs 3rd/4th, the group loses overall.
    assert sum(losers) < 0 and sorted(losers) == [-24, -8, 8]
    week = iso_week_id(container.clock.now_ms())
    weekly = container.store._docs[f"weekly_user_stats/{week}_u1"]
    assert weekly["ranked_weekly_xp"] == 200 and weekly["quick_ranked_wins"] == 1 and weekly["league"] == "BRONZE"
    assert weekly["group_id"] == u1["league_state"]["group_id"]
    board = players.get("/v1/leaderboards/weekly", "u2").json()
    assert board["entries"][0]["public_id"] == u1["public_id"] and board["entries"][0]["rank"] == 1
    assert board["me"]["rank"] >= 2 and len(board["entries"]) == 4
    league = players.get("/v1/league", "u1").json()
    assert league["league"] == "BRONZE" and league["joined"] is True and len(league["standings"]) == 100
    mine = [row for row in league["standings"] if row["me"]]
    assert len(mine) == 1 and mine[0]["weekly_xp"] == 200 and league["rank"] == mine[0]["rank"]
    assert "mmr" not in league and league["ranked_weekly_xp"] == 200


def test_ranked_loss_resets_streak(players, container):
    container.store._docs["users/u2"]["quick_current_ranked_win_streak"] = 3
    match_id = ranked_match(players, container)
    for _ in range(10):
        play_round_human_wins(players, container, match_id, uid="u1")
    assert user(container, "u2")["quick_current_ranked_win_streak"] == 0


def test_settlement_is_idempotent(players, container):
    match_id = bot_fill_match(players, container)
    for _ in range(10):
        play_round_human_wins(players, container, match_id)
    before = dict(user(container, "u1"))
    shard = container.store._docs[f"match_index/{match_id}"]["rtdb_shard_id"]
    asyncio.run(container.settlement.run(match_id, shard))
    asyncio.run(container.settlement.run(match_id, shard))
    assert user(container, "u1")["total_xp"] == before["total_xp"]
    stats = container.store.dump("question_stats_shards/")
    assert sum(int(d.get("shown", 0)) for d in stats.values()) == 10


def test_mission_claim_is_idempotent(players, container):
    daily = players.get("/v1/missions/daily", "u1").json()
    mission_id = daily["missions"][0]["mission_id"]
    res = players.post(f"/v1/missions/{mission_id}/claim", "u1")
    assert res.status_code == 409 and res.json()["error"]["code"] == "MISSION_NOT_COMPLETE"
    doc_path = f"user_missions/u1_{daily['period_id']}"
    container.store._docs[doc_path]["missions"][0].update(progress=99, completed=True)
    first = players.post(f"/v1/missions/{mission_id}/claim", "u1").json()
    assert first["xp_awarded"] == 30 and user(container, "u1")["total_xp"] == 30
    again = players.post(f"/v1/missions/{mission_id}/claim", "u1").json()
    assert again["xp_awarded"] == 0 and user(container, "u1")["total_xp"] == 30


def test_leaderboard_tiebreak_order(players, container):
    week = iso_week_id(container.clock.now_ms())
    rows = [("u1", 300, 1, 0, "b"), ("u2", 300, 2, 0, "z"), ("u3", 300, 2, 0, "a"), ("u4", 500, 0, 0, "m")]
    for uid, xp, wins, crowns, tb in rows:
        container.store._docs[f"weekly_user_stats/{week}_{uid}"] = {
            "uid": uid, "week_id": week, "ranked_weekly_xp": xp, "quick_ranked_wins": wins,
            "survival_ranked_crowns": crowns, "tie_break_hash": tb, "public_id": uid, "league": "GOLD"}
    board = players.get("/v1/leaderboards/weekly", "u1").json()
    assert [e["public_id"] for e in board["entries"]] == ["u4", "u3", "u2", "u1"]
    assert board["me"]["rank"] == 4
    filtered = players.get("/v1/leaderboards/weekly", "u1", league="SILVER").json()
    assert filtered["entries"] == [] and filtered["me"] is None


# ---------------------------------------------------------------------------------------------- reactions


def active_round(players, container, match_id):
    pub = public(container, match_id)
    container.clock.set(pub["starts_at_ms"] + 200)
    return pub["round_id"]


def test_reaction_once_per_round_and_catalog_only(players, container):
    match_id = bot_fill_match(players, container)
    round_id = active_round(players, container, match_id)
    res = players.post(f"/v1/matches/{match_id}/reaction", "u1", {"round_id": round_id, "reaction_id": "emoji_fire"})
    assert res.status_code == 200 and res.json()["accepted"] is True
    events = [e for e in public(container, match_id)["events"] if e["type"] == "REACTION"]
    assert events[-1]["value"] == "emoji_fire" and events[-1]["pid"] == container.profiles.public_id("u1")
    again = players.post(f"/v1/matches/{match_id}/reaction", "u1", {"round_id": round_id, "reaction_id": "text_gg"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "REACTION_ALREADY_USED"
    bad = players.post(f"/v1/matches/{match_id}/reaction", "u1", {"round_id": round_id, "reaction_id": "lol free"})
    assert bad.status_code == 400
    # Reactions never change score or answer state.
    assert public(container, match_id)["participants"][container.profiles.public_id("u1")]["score"] == 0


def test_blocked_players_reactions_are_muted_for_each_other(players, container):
    match_id = ranked_match(players, container)
    round_id = active_round(players, container, match_id)
    pid_u1 = container.profiles.public_id("u1")
    assert players.post(f"/v1/blocks/{pid_u1}", "u2").status_code == 200  # block created mid-match
    res = players.post(f"/v1/matches/{match_id}/reaction", "u1", {"round_id": round_id, "reaction_id": "text_wow"})
    assert res.status_code == 200
    root = live_root(container, match_id)
    assert root["player_private"]["u2"]["muted_pids"] == [pid_u1]
    assert root["player_private"]["u1"]["muted_pids"] == [container.profiles.public_id("u2")]
    assert "muted_pids" not in root["player_private"]["u3"]


def test_eliminated_survival_spectator_can_react(players, container):
    res = join(players, "u1", mode="survival")
    container.clock.set(res.json()["human_fill_at_ms"])
    match_id = players.get("/v1/matchmaking/status", "u1").json()["match"]["match_id"]
    pub = public(container, match_id)
    container.clock.set(pub["ends_at_ms"] + 400)
    run_tasks(container)  # u1 did not answer: eliminated
    pub = public(container, match_id)
    if pub["state"] == "ROUND_RESOLVE":
        container.clock.set(pub["reveal_ends_at_ms"] + 60)
        run_tasks(container)
    pub = public(container, match_id)
    if pub["state"] in ("ROUND_LOADING", "ROUND_ACTIVE"):
        assert private(container, match_id, "u1")["own_answer_status"] == "INELIGIBLE"
        res = players.post(f"/v1/matches/{match_id}/reaction", "u1", {"round_id": pub["round_id"],
                                                                       "reaction_id": "emoji_clap"})
        assert res.status_code == 200


# ---------------------------------------------------------------------------------------------- question reports


def test_question_report_from_match_is_deduplicated(players, container):
    match_id = bot_fill_match(players, container)
    round_id = public(container, match_id)["round_id"]
    body = {"round_id": round_id, "reason": "WRONG_ANSWER"}
    first = players.post(f"/v1/matches/{match_id}/question-report", "u1", body)
    assert first.status_code == 200 and first.json()["duplicate"] is False
    second = players.post(f"/v1/matches/{match_id}/question-report", "u1", body)
    assert second.json()["duplicate"] is True
    outsider = players.post(f"/v1/matches/{match_id}/question-report", "u2", body)
    assert outsider.status_code == 403


def test_auto_quarantine_removes_version_from_manifests(container):
    gid = next(p.split("/")[1] for p, d in container.store._docs.items()
               if p.startswith("question_groups/") and d.get("status") == "ACTIVE")
    version = container.store._docs[f"question_groups/{gid}"]["version"]

    async def run():
        for i in range(10):
            await container.question_reports.report(f"r{i}", gid=gid, version=version, language="en",
                                                    mode="QUICK", reason=QuestionReportReason.AMBIGUOUS,
                                                    match_id=None)

    asyncio.run(run())
    assert container.store._docs[f"question_groups/{gid}"]["status"] == "QUARANTINED"
    assert f"moderation_queue/question_{gid}_{version}" in container.store._docs

    async def manifest_gids():
        gids = set()
        for mode in ("QUICK", "SURVIVAL"):
            for d in ("EASY", "MEDIUM", "HARD"):
                gids |= {e.gid for e in await container.manifest_cache.get("en", mode, d)}
        return gids

    assert gid not in asyncio.run(manifest_gids())


def test_below_threshold_reports_do_not_quarantine(container):
    gid = next(p.split("/")[1] for p, d in container.store._docs.items()
               if p.startswith("question_groups/") and d.get("status") == "ACTIVE")
    version = container.store._docs[f"question_groups/{gid}"]["version"]

    async def run():
        for i in range(9):
            await container.question_reports.report(f"r{i}", gid=gid, version=version, language="en",
                                                    mode="QUICK", reason=QuestionReportReason.OTHER, match_id=None)

    asyncio.run(run())
    assert container.store._docs[f"question_groups/{gid}"]["status"] == "ACTIVE"


def test_deleting_match_player_finishes_via_tasks(players, container):
    match_id = bot_fill_match(players, container)
    run_until_finished(container, match_id)
    assert user(container, "u1")["matches_completed"] == 1


def test_level_milestone_unlocks_a_frame_and_names_the_next_reward(players, container):
    container.store._docs["users/u1"]["total_xp"] = 250  # a 200 XP win crosses level 3 (303 XP)
    match_id = bot_fill_match(players, container)
    for _ in range(10):
        play_round_human_wins(players, container, match_id)
    u = user(container, "u1")
    assert "frame_level_3" in u["frame_ids"] and "frame_level_5" not in u["frame_ids"]
    settlement = private(container, match_id, "u1")["settlement"]
    assert settlement["progress_new_frames"] == ["frame_level_3"]
    assert settlement["progress_next_level_reward"] == {"level": 5, "frame_id": "frame_level_5"}
    profile = players.get("/v1/profile", "u1").json()["profile"]
    assert profile["next_level_reward"] == {"level": 5, "frame_id": "frame_level_5"}
    frames = {f["id"]: f for f in players.get("/v1/cosmetics", "u1").json()["frames"]}
    assert frames["frame_level_3"]["level"] == 3
