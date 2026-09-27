"""Builders for pure-engine tests: synthetic plans, rosters and deterministic bot plans."""

from __future__ import annotations

from typing import Any

from app.common.keys import Keyring
from app.common.server_config import GameConfig
from app.matches import engine
from app.matches.model import Mode
from tests.conftest import make_settings

KEYS = Keyring.from_settings(make_settings())
T0 = 1_800_000_000_000


def item(n: int, difficulty: str = "MEDIUM", category: str = "history") -> dict[str, Any]:
    return {
        "qid": n, "gid": f"g{n}", "v": 1, "difficulty": difficulty, "category_id": category,
        "subcategory_id": "empires", "text": f"Question {n}?",
        "options": [{"concept_id": f"c{n}_{k}", "text": f"Option {k}"} for k in "abcd"],
        "correct": f"c{n}_a", "media": None,
    }


def quick_plan() -> dict[str, Any]:
    order = ["EASY", "EASY"] + ["MEDIUM"] * 5 + ["HARD"] * 3
    return {"normal": [item(i + 1, d) for i, d in enumerate(order)],
            "reserve": [item(100 + i, d) for i, d in enumerate(["MEDIUM", "HARD", "HARD", "HARD", "HARD"])]}


def survival_plan(per: int = 20) -> dict[str, Any]:
    return {"pools": {d: [item(1000 + k * 100 + i, d) for i in range(per)]
                      for k, d in enumerate(["EASY", "MEDIUM", "HARD"])}}


def roster(humans: int, bots: int) -> list[dict[str, Any]]:
    members = [{"pid": f"ph{i}", "kind": "HUMAN", "uid": f"u{i}", "username": f"human{i}", "avatar_id": "av_001",
                "pre_match_mmr": 1000} for i in range(humans)]
    members += [{"pid": f"pb{i}", "kind": "BOT", "bot_id": f"bot{i}", "username": f"bot_name{i}",
                 "avatar_id": "av_002", "pre_match_mmr": 1000} for i in range(bots)]
    return members


def never_answering_profile() -> dict[str, Any]:
    profile = GameConfig().bots.profiles["NORMAL"].model_dump()
    profile["answer_rate"] = 0.0
    return profile


def new_match(mode: Mode = Mode.QUICK, humans: int = 4, bots: int = 0, bot_profile: dict | None = None,
              now: int = T0) -> tuple[dict[str, Any], engine.StepResult]:
    config = GameConfig()
    members = roster(humans, bots)
    profiles = {m["pid"]: (bot_profile or never_answering_profile()) for m in members if m["kind"] == "BOT"}
    return engine.create_match_state(
        keys=KEYS, match_id="m-test", shard_id="live-00", mode=mode, language="en", region="europe-west1",
        roster=members, plan=quick_plan() if mode == Mode.QUICK else survival_plan(),
        config_snapshot=config.match_snapshot(mode.value), bot_profiles=profiles, reaction_ids=["text_gg"],
        ranked={"eligible": humans >= 3, "reason": "test", "human_slots": humans, "bot_slots": bots},
        source="TEST", now_ms=now)


def start_round(state: dict[str, Any]) -> int:
    """Advance the loading round to active; returns starts_at."""
    rnd = state["round"]
    engine.resolve_due(state, KEYS, rnd["starts_at_ms"], "TEST")
    return rnd["starts_at_ms"]


def answer(state: dict[str, Any], uid: str, correct: bool, at_ms: int, request_id: str | None = None):
    rnd = state["round"]
    pid = next(pid for pid, p in state["participants"].items() if p.get("uid") == uid)
    concepts = [o["concept_id"] for o in rnd["options"]]
    concept = rnd["correct"] if correct else next(c for c in concepts if c != rnd["correct"])
    del pid
    return engine.apply_answer(state, KEYS, uid=uid, round_id=rnd["round_id"], option_id=concept,
                               received_at_ms=at_ms, request_id=request_id or f"req-{uid}-{rnd['round_id']}")


def finish_round_without_answers(state: dict[str, Any]) -> None:
    rnd = state["round"]
    engine.resolve_due(state, KEYS, rnd["ends_at_ms"] + engine.GRACE_MS, "TEST")
    advance(state)


def advance(state: dict[str, Any]) -> engine.StepResult:
    rnd = state["round"]
    return engine.resolve_due(state, KEYS, rnd["reveal_ends_at_ms"], "TEST")
