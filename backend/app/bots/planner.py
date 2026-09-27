"""Precommitted, immutable bot round plans (spec §23.3).

Seed = HMAC(bot_plan_secret, match_id:round_id:bot_id:question_version). A plan is computed before the round
is published and never changes because a human is winning or losing. Bots choose concept IDs, never positions.
"""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any

from app.common.keys import HmacKey
from app.common.server_config import BotProfileConfig


def plan_seed(key: HmacKey, match_id: str, round_id: str, bot_id: str, question_version: str) -> int:
    return int.from_bytes(key.digest(f"{match_id}:{round_id}:{bot_id}:{question_version}")[:8], "big")


def commit_hash(plan: dict[str, Any]) -> str:
    body = {k: v for k, v in plan.items() if k != "commit_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def plan_bot_round(
    key: HmacKey,
    *,
    match_id: str,
    round_id: str,
    bot_id: str,
    question_version: str,
    profile: BotProfileConfig,
    difficulty: str,
    option_concepts: list[str],
    correct_concept: str,
    starts_at_ms: int,
    duration_ms: int,
    reaction_ids: list[str],
    reaction_probability: float,
) -> dict[str, Any]:
    rng = random.Random(plan_seed(key, match_id, round_id, bot_id, question_version))
    will_answer = rng.random() < profile.answer_rate
    will_be_correct = will_answer and rng.random() < profile.accuracy.get(difficulty, 0.5)
    wrong = [c for c in option_concepts if c != correct_concept]
    selected = correct_concept if will_be_correct else (rng.choice(wrong) if will_answer and wrong else None)
    scale = duration_ms / 11_000
    mean = profile.response_mean_ms.get(difficulty, 5000) * scale
    offset = rng.gauss(mean, profile.response_sd_ms * scale)
    # Realistic human-like range: never consistently sub-second, never after the deadline.
    offset = int(min(max(offset, profile.response_min_ms), duration_ms - 150))
    plan: dict[str, Any] = {
        "bot_id": bot_id,
        "round_id": round_id,
        "will_answer": will_answer,
        "will_be_correct": will_be_correct,
        "response_at_ms": starts_at_ms + offset,
    }
    if selected is not None:
        plan["selected_concept_id"] = selected
    if reaction_ids and rng.random() < reaction_probability:
        plan["optional_reaction_id"] = rng.choice(reaction_ids)
    plan["commit_hash"] = commit_hash(plan)
    return plan
