"""Weekly cohort leagues and the ranked bootstrap (playtest 2026-09-27)."""

from __future__ import annotations

from app.common.clock import iso_week_id
from app.common.server_config import GameConfig, LeagueConfig, RankedConfig
from app.matches.factory import ranked_eligibility
from app.matches.model import Mode
from app.progression.service import weekly_path
from app.ranking.league_groups import bot_identities, bot_weekly_xp, previous_week, week_bounds

DAY = 86_400_000


async def _use(container, **league) -> LeagueConfig:
    config = GameConfig(leagues=LeagueConfig(**league))
    await container.config.publish(config, "test", container.clock.now_ms())
    return config.leagues


async def _user(container, uid: str, tier: str = "BRONZE") -> None:
    await container.store.set(f"users/{uid}", {"uid": uid, "public_id": f"p_{uid}", "username_display": uid,
                                               "avatar_id": "av_001", "league_tier": tier})


async def _xp(container, uid: str, xp: int) -> None:
    week = iso_week_id(container.clock.now_ms())
    await container.store.set(weekly_path(week, uid), {"uid": uid, "week_id": week, "ranked_weekly_xp": xp})


def test_bootstrap_makes_public_bot_matches_ranked_only_when_enabled():
    ranked = RankedConfig()
    assert ranked_eligibility(Mode.QUICK, 1, 3, ranked, "PUBLIC")["eligible"] is False
    boot = ranked_eligibility(Mode.QUICK, 1, 3, ranked, "PUBLIC", bootstrap=True)
    assert boot["eligible"] is True and boot["reason"] == "bootstrap"
    # Friend challenges never count, bootstrap or not.
    assert ranked_eligibility(Mode.QUICK, 1, 3, ranked, "FRIEND", bootstrap=True)["eligible"] is False


async def test_bootstrap_switches_off_once_enough_humans_played(container):
    await _use(container, bootstrap_active_humans=2)
    now = container.clock.now_ms()
    assert await container.leagues.bootstrap_active(now) is True
    for uid in ("a", "b"):
        await _user(container, uid)
        await container.leagues.ensure_group(uid, now)
    assert await container.leagues.active_humans(now) == 2
    assert await container.leagues.bootstrap_active(now) is False


async def test_first_player_gets_a_full_group_of_bots_and_humans_take_bot_seats(container):
    await _use(container, group_size=10, promote=2, demote=2)
    now = container.clock.now_ms()
    await _user(container, "u1")
    group_id = await container.leagues.ensure_group("u1", now)
    assert group_id == await container.leagues.ensure_group("u1", now)  # idempotent within the week
    rows = await container.leagues.standings(group_id, now)
    assert len(rows) == 10 and sum(1 for r in rows if r["uid"]) == 1
    for i in range(2, 11):
        await _user(container, f"u{i}")
        assert await container.leagues.ensure_group(f"u{i}", now) == group_id
    rows = await container.leagues.standings(group_id, now)
    assert len(rows) == 10 and all(r["uid"] for r in rows)
    await _user(container, "u11")
    assert await container.leagues.ensure_group("u11", now) != group_id  # the full group is closed


async def test_view_marks_zones_and_hides_bot_identity(container):
    await _use(container, group_size=10, promote=3, demote=3)
    now = container.clock.now_ms()
    await _user(container, "u1", tier="SILVER")
    await container.leagues.ensure_group("u1", now)
    await _xp(container, "u1", 5_000)
    view = await container.leagues.view("u1", now)
    assert view["league"] == "SILVER" and view["joined"] and view["rank"] == 1
    assert [r["zone"] for r in view["standings"]][:3] == ["PROMOTE"] * 3
    assert [r["zone"] for r in view["standings"]][-3:] == ["DEMOTE"] * 3
    assert all(set(r) == {"rank", "public_id", "username", "avatar_id", "frame_id", "weekly_xp", "me", "zone"}
               for r in view["standings"])
    bronze = await container.leagues.view("nobody", now)
    assert bronze["league"] == "BRONZE" and bronze["joined"] is False and bronze["demote_count"] == 0


def test_bot_weekly_xp_grows_over_the_week():
    week = "2026-W40"
    start, end = week_bounds(week)
    seat = {"target_xp": 1000, "start": 0.2}
    assert bot_weekly_xp(seat, week, start) == 0
    assert bot_weekly_xp(seat, week, start + int(0.2 * (end - start))) == 0
    assert 0 < bot_weekly_xp(seat, week, start + (end - start) // 2) < 1000
    assert bot_weekly_xp(seat, week, end + DAY) == 1000
    assert previous_week(week) == "2026-W39"


async def _finish_week(container, uid: str, tier: str, xp: int) -> dict:
    await _user(container, uid, tier=tier)
    await container.leagues.ensure_group(uid, container.clock.now_ms())
    await _xp(container, uid, xp)
    _, end = week_bounds(iso_week_id(container.clock.now_ms()))
    container.clock.set(end + DAY)
    return await container.leagues.roll_over(uid, container.clock.now_ms())


async def test_top_of_the_group_is_promoted(container):
    await _use(container, group_size=10, promote=2, demote=2)
    fields = await _finish_week(container, "u1", "GOLD", 1_000_000)
    assert fields["league_tier"] == "PLATINUM"
    assert fields["league_state"]["last_result"]["outcome"] == "PROMOTED"
    assert (await container.store.get("users/u1"))["league_tier"] == "PLATINUM"


async def test_bottom_of_the_group_is_relegated_but_never_below_bronze(container):
    await _use(container, group_size=10, promote=2, demote=2)
    fields = await _finish_week(container, "u1", "GOLD", 0)
    assert fields["league_tier"] == "SILVER" and fields["league_state"]["last_result"]["outcome"] == "RELEGATED"
    container.clock.set(0)
    fields = await _finish_week(container, "u2", "BRONZE", 0)
    assert fields["league_tier"] == "BRONZE" and fields["league_state"]["last_result"]["outcome"] == "STAYED"


async def test_bots_never_take_a_players_username(container):
    await _use(container, group_size=10)
    taken = bot_identities("BRONZE")
    for bot in taken:
        await container.store.set(f"username_registry/{bot['username']}", {"uid": "human", "state": "ACTIVE"})
    await _user(container, "u1")
    group_id = await container.leagues.ensure_group("u1", container.clock.now_ms())
    rows = await container.leagues.standings(group_id, container.clock.now_ms())
    assert [r["uid"] for r in rows] == ["u1"]  # every bot name was owned by a human, so no bot seat


async def test_deleted_player_leaves_their_league_group(container):
    await _use(container, group_size=10)
    await _user(container, "u1")
    group_id = await container.leagues.ensure_group("u1", container.clock.now_ms())
    await container.deletion.complete("u1")
    assert (await container.store.get(f"league_groups/{group_id}"))["human_uids"] == []


def test_bootstrap_bot_match_is_ranked_and_puts_the_player_in_a_league(api, container):
    import asyncio

    from tests.unit.test_matchmaking import bot_fill_match, live_root, play_round_human_wins

    asyncio.run(_use(container, group_size=10))
    api.onboard("u1")
    match_id = bot_fill_match(api, container)
    ranked = live_root(container, match_id)["authoritative"]["ranked"]
    assert ranked["eligible"] is True and ranked["reason"] == "bootstrap"
    for _ in range(10):
        play_round_human_wins(api, container, match_id)
    league = api.get("/v1/league", "u1").json()
    assert league["joined"] is True and league["ranked_weekly_xp"] > 0 and len(league["standings"]) == 10
