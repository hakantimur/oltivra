"""Settlement progression (spec §7, §33): XP, levels, MMR/league/placement, streaks, crowns, weekly stats,
missions, badges/frames, category stats, question statistic intents, reward eligibility and progression events.

Everything is computed from the immutable final match result and config snapshot in the authoritative
state. ``read`` performs every transaction read; ``apply`` performs the writes (Firestore ordering rule).
"""

from __future__ import annotations

import logging
from typing import Any

from app.catalog.data import level_frames, next_level_reward
from app.common.clock import iso_week_id, ms_to_datetime
from app.common.ids import sha256_hex
from app.matches.model import Mode, humans, participants
from app.missions.service import apply_metrics, generate, mission_path, period_ids
from app.moderation.sanctions import ranked_restricted
from app.profiles.service import user_path
from app.progression.xp import completed_survival_rounds, quick_base_xp, survival_base_xp
from app.questions.stats import StatIntent
from app.ranking.elo import Seat, rating_deltas
from app.ranking.leagues import League, tier_of
from app.ranking.levels import level_for_xp

REWARD_RETAIN_MS = 86_400_000
log = logging.getLogger("oltivra.progression")

SPECIALIST_CORRECT = 100
LEAGUE_ORDER = [lg.value for lg in League]
SPECIALIST_BADGES = {"geography": "badge_geography_specialist", "science_nature": "badge_science_specialist"}


def weekly_path(week_id: str, uid: str) -> str:
    return f"weekly_user_stats/{week_id}_{uid}"


def category_path(uid: str) -> str:
    return f"user_category_stats/{uid}"


def intents_path(match_id: str) -> str:
    return f"question_stat_intents/{match_id}"


def question_stat_intents(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Human-only answer statistics per question version (bots never count, spec §10.3)."""
    human_pids = set(humans(state))
    intents = []
    quick = state["mode"] == Mode.QUICK
    for entry in state.get("round_log") or []:
        answers = entry.get("answers") or {}
        eligible = [pid for pid in entry.get("eligible") or [] if pid in human_pids]
        if not eligible:
            continue
        counts = {"shown": len(eligible), "attempted": 0, "correct": 0, "wrong": 0, "no_answer": 0,
                  "censored_by_early_quick_winner": 0, "sum_response_ms": 0}
        for pid in eligible:
            answer = answers.get(pid)
            if answer:
                counts["attempted"] += 1
                counts["correct" if answer["c"] else "wrong"] += 1
                counts["sum_response_ms"] += int(answer["ms"])
            elif quick and entry.get("winner"):
                counts["censored_by_early_quick_winner"] += 1
            else:
                counts["no_answer"] += 1
        intents.append({"gid": entry["gid"], "v": entry["v"], "counts": counts})
    return intents


def _badges(user: dict[str, Any], league: str, categories: dict[str, Any]) -> tuple[set[str], set[str]]:
    badges, frames = set(), set()
    if user.get("quick_wins_lifetime", 0) >= 1:
        badges.add("badge_first_quick_win")
    if user.get("quick_ranked_wins_lifetime", 0) >= 10:
        badges.add("badge_10_ranked_quick_wins")
    if user.get("quick_best_ranked_win_streak", 0) >= 5:
        badges.add("badge_5_ranked_streak")
        frames.add("frame_streak_5")
    if user.get("survival_ranked_crowns_lifetime", 0) >= 1:
        badges.add("badge_first_crown")
        frames.add("frame_crown")
    if user.get("survival_ranked_crowns_lifetime", 0) >= 10:
        badges.add("badge_10_crowns")
    for category, badge in SPECIALIST_BADGES.items():
        if int((categories.get(category) or {}).get("correct", 0)) >= SPECIALIST_CORRECT:
            badges.add(badge)
    if league in LEAGUE_ORDER and LEAGUE_ORDER.index(league) >= LEAGUE_ORDER.index(League.DIAMOND.value):
        badges.add("badge_diamond_league")
        frames.add("frame_diamond")
    if league == League.LEGEND.value:
        badges.add("badge_legend_league")
        frames.add("frame_legend")
    frames |= level_frames(level_for_xp(int(user.get("total_xp", 0))))
    return badges, frames


class ProgressionHooks:
    def __init__(self, container) -> None:
        self._c = container

    # ------------------------------------------------------------------------------------------ reads
    def read(self, txn, state: dict[str, Any], results: dict[str, Any], users: dict[str, Any],
             config) -> dict[str, Any]:
        finished = int(state.get("finished_at_ms") or state.get("created_at_ms") or 0)
        week = iso_week_id(finished)
        periods = period_ids(finished)
        uids = [uid for uid in users if users[uid]]
        paths: list[str] = []
        for uid in uids:
            paths += [weekly_path(week, uid), category_path(uid), mission_path(uid, periods["DAILY"]),
                      mission_path(uid, periods["WEEKLY"])]
        docs = txn.get_many(paths) if paths else []
        prepared: dict[str, Any] = {"week": week, "periods": periods, "finished": finished, "users": users,
                                    "config": config, "by_uid": {}}
        for index, uid in enumerate(uids):
            weekly, categories, daily, weekly_missions = docs[index * 4:index * 4 + 4]
            prepared["by_uid"][uid] = {"weekly": weekly, "categories": categories, "daily": daily,
                                       "weekly_missions": weekly_missions}
        return prepared

    # ------------------------------------------------------------------------------------------ writes
    def apply(self, txn, state: dict[str, Any], results: dict[str, Any], prepared: dict[str, Any], now: int) -> None:
        c = self._c
        match_id = state["match_id"]
        mode = state["mode"]
        ranked = bool((state.get("ranked") or {}).get("eligible"))
        ranked_cfg = (state.get("config") or {}).get("ranked") or {}
        deltas = self._mmr_deltas(state, results, prepared["users"], ranked_cfg) if ranked else {}
        for uid, extra in prepared["by_uid"].items():
            user = dict(prepared["users"][uid])
            # A ranked-restricted player still plays, but the result never moves their rating (spec §28.4).
            user_ranked = ranked and not ranked_restricted(user, now)
            result = results[uid]
            pid = result["pid"]
            participant = participants(state)[pid]
            place, left = result["place"], result["left"]
            if mode == Mode.QUICK:
                base_xp = quick_base_xp(int(participant.get("score", 0)), place, left)
                rounds = 0
            else:
                rounds = completed_survival_rounds(state.get("round_log") or [], pid)
                base_xp = survival_base_xp(rounds, place, left)
            won = place == 1 and not left
            before_level = level_for_xp(int(user.get("total_xp", 0)))
            # The tier changes only at the weekly rollover (app.ranking.league_groups).
            before_league = tier_of(user).value
            user["total_xp"] = int(user.get("total_xp", 0)) + base_xp
            user["matches_completed"] = int(user.get("matches_completed", 0)) + 1
            if mode == Mode.QUICK and won:
                user["quick_wins_lifetime"] = int(user.get("quick_wins_lifetime", 0)) + 1
            delta = 0
            if user_ranked:
                delta = deltas.get(uid, 0)
                user["mmr"] = int(user.get("mmr", 1000)) + delta
                user["ranked_matches_completed"] = int(user.get("ranked_matches_completed", 0)) + 1
                if mode == Mode.QUICK:
                    if won:
                        streak = int(user.get("quick_current_ranked_win_streak", 0)) + 1
                        user["quick_current_ranked_win_streak"] = streak
                        user["quick_best_ranked_win_streak"] = max(streak,
                                                                   int(user.get("quick_best_ranked_win_streak", 0)))
                        user["quick_ranked_wins_lifetime"] = int(user.get("quick_ranked_wins_lifetime", 0)) + 1
                    else:  # a ranked loss or voluntary abandonment resets the streak (spec §7.7)
                        user["quick_current_ranked_win_streak"] = 0
                elif won:
                    user["survival_ranked_crowns_lifetime"] = int(user.get("survival_ranked_crowns_lifetime", 0)) + 1
            after_league = before_league
            # Category performance (all completed matches, spec §7.4).
            categories = dict((extra["categories"] or {}).get("categories") or {})
            correct_answers = 0
            for entry in state.get("round_log") or []:
                answer = (entry.get("answers") or {}).get(pid)
                if pid not in (entry.get("eligible") or []):
                    continue
                cat = dict(categories.get(entry["category_id"]) or {"seen": 0, "answered": 0, "correct": 0,
                                                                     "sum_correct_ms": 0})
                cat["seen"] += 1
                if answer:
                    cat["answered"] += 1
                    if answer["c"]:
                        cat["correct"] += 1
                        cat["sum_correct_ms"] += int(answer["ms"])
                        correct_answers += 1
                categories[entry["category_id"]] = cat
            txn.set(category_path(uid), {"schema_version": 1, "uid": uid, "categories": categories,
                                         "updated_at_ms": now})
            # Missions: progress never doubled by rewarded XP.
            metrics = {
                "matches_played": 1, "correct_answers": correct_answers,
                "reactions_sent": int(participant.get("reactions_sent", 0)),
                "quick_played": int(mode == Mode.QUICK), "survival_played": int(mode == Mode.SURVIVAL),
                "quick_question_wins": int(participant.get("wins", 0)) if mode == Mode.QUICK else 0,
                "quick_points": max(int(participant.get("score", 0)), 0) if mode == Mode.QUICK else 0,
                "quick_ranked_wins": int(user_ranked and mode == Mode.QUICK and won),
                "survival_ranked_top3": int(user_ranked and mode == Mode.SURVIVAL and place is not None and place <= 3
                                            and not left),
                "survival_rounds": rounds,
            }
            config = prepared["config"]
            missions_completed: list[str] = []
            for period, key in (("DAILY", "daily"), ("WEEKLY", "weekly_missions")):
                doc = extra[key] or generate(c.keys, uid, period, prepared["periods"][period], prepared["finished"],
                                             config)
                missions_completed += apply_metrics(doc, metrics, now)
                txn.set(mission_path(uid, doc["period_id"]), doc)
            # Badges and frames (cosmetic only).
            badges, frames = _badges(user, after_league, categories)
            new_badges = sorted(badges - set(user.get("badge_ids") or []))
            user["badge_ids"] = list(user.get("badge_ids") or []) + new_badges
            new_frames = sorted(frames - set(user.get("frame_ids") or []))
            user["frame_ids"] = list(user.get("frame_ids") or ["frame_none"]) + new_frames
            sequence = int(user.get("progression_sequence", 0)) + 1
            user["progression_sequence"] = sequence
            fields = {k: user[k] for k in (
                "total_xp", "matches_completed", "quick_wins_lifetime", "mmr", "ranked_matches_completed",
                "quick_current_ranked_win_streak", "quick_best_ranked_win_streak",
                "quick_ranked_wins_lifetime", "survival_ranked_crowns_lifetime", "badge_ids", "frame_ids",
                "progression_sequence") if k in user}
            txn.update(user_path(uid), fields)
            txn.set(f"public_profiles/{user['public_id']}", c.profiles.public_profile(user))
            if user_ranked:
                weekly = dict(extra["weekly"] or {"schema_version": 1, "uid": uid, "week_id": prepared["week"],
                                                  "ranked_weekly_xp": 0, "quick_ranked_wins": 0,
                                                  "survival_ranked_crowns": 0,
                                                  "tie_break_hash": sha256_hex(f"weekly:{uid}")[:16]})
                weekly["ranked_weekly_xp"] = int(weekly["ranked_weekly_xp"]) + base_xp
                weekly["quick_ranked_wins"] = int(weekly["quick_ranked_wins"]) + int(mode == Mode.QUICK and won)
                weekly["survival_ranked_crowns"] = int(weekly["survival_ranked_crowns"]) + int(
                    mode == Mode.SURVIVAL and won)
                weekly.update(league=after_league, group_id=(user.get("league_state") or {}).get("group_id"),
                              public_id=user["public_id"],
                              username=user.get("username_display"), avatar_id=user.get("avatar_id"),
                              frame_id=user.get("frame_id", "frame_none"), updated_at_ms=now,
                              expires_at=ms_to_datetime(now + 400 * 86_400_000))
                txn.set(weekly_path(prepared["week"], uid), weekly)
            # Rewarded XP eligibility: one offer per settled match (spec §7.2, §31.2), only while the feature is on.
            reward_offer = prepared["config"].features.rewarded_offers_enabled
            if reward_offer:
                txn.set(f"reward_offers/{match_id}_{uid}", {
                    "schema_version": 1, "match_id": match_id, "uid": uid, "state": "ELIGIBLE", "base_xp": base_xp,
                    "created_at_ms": now, "eligible_until_ms": now + prepared["config"].economy.reward_offer_ttl_ms,
                    # Firestore TTL (spec §16.4); grants stay auditable in reward_transactions.
                    "expires_at": ms_to_datetime(
                        now + prepared["config"].economy.reward_offer_ttl_ms + REWARD_RETAIN_MS)})
            txn.set(f"progression_events/{uid}_{sequence:08d}", {
                "schema_version": 1, "uid": uid, "sequence": sequence, "match_id": match_id, "kind": "MATCH_SETTLED",
                "xp": base_xp, "ranked": ranked, "mmr_delta": delta, "badges": new_badges, "at_ms": now})
            result.update(
                xp_awarded=base_xp, mmr_delta=delta, survival_rounds=rounds,
                progress_level_before=before_level, progress_level_after=level_for_xp(user["total_xp"]),
                progress_total_xp=user["total_xp"], progress_league_before=before_league,
                progress_league_after=after_league, progress_ranked=ranked,
                progress_streak=int(user.get("quick_current_ranked_win_streak", 0)),
                progress_new_badges=new_badges, progress_new_frames=new_frames,
                progress_next_level_reward=next_level_reward(level_for_xp(user["total_xp"])),
                progress_missions_completed=missions_completed,
                progress_reward_offer=reward_offer)
        txn.set(intents_path(match_id), {"schema_version": 1, "match_id": match_id, "language": state["language"],
                                         "mode": mode, "intents": question_stat_intents(state), "applied": False,
                                         "created_at_ms": now})

    def _mmr_deltas(self, state: dict[str, Any], results: dict[str, Any], users: dict[str, Any],
                    ranked_cfg: dict[str, Any]) -> dict[str, int]:
        seats = []
        for key, result in results.items():
            participant = participants(state)[result["pid"]]
            if result["place"] is None:
                continue
            seats.append(Seat(key, float(participant["pre_match_mmr"]), int(result["place"]), result["is_bot"]))
        base_k = ranked_cfg.get("quick_k", 32) if state["mode"] == Mode.QUICK else ranked_cfg.get("survival_k", 40)
        provisional = {uid: int((users.get(uid) or {}).get("ranked_matches_completed", 0))
                       < int(ranked_cfg.get("provisional_matches", 20)) for uid in users}
        return rating_deltas(seats, float(base_k), provisional, float(ranked_cfg.get("provisional_multiplier", 1.5)))

    # ------------------------------------------------------------------------------------------ after commit
    async def after_commit(self, match_id: str) -> None:
        """Apply sharded question stats once (at-most-once: statistics tolerate a lost batch)."""
        c = self._c

        def claim(txn) -> dict[str, Any] | None:
            doc = txn.get(intents_path(match_id))
            if not doc or doc.get("applied"):
                return None
            txn.update(intents_path(match_id), {"applied": True})
            return doc

        doc = await c.store.run_transaction(claim)
        if not doc:
            return
        await c.question_stats.apply([StatIntent(i["gid"], int(i["v"]), doc["language"], doc["mode"], i["counts"])
                                      for i in doc["intents"]])
