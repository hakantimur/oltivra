"""Versioned server-only game configuration (spec §32.2).

Stored at ``server_config/active`` (pointer to the version) and ``server_config/v{n}``; cached with version
checking. Every match snapshots the relevant values into authoritative state and match history.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.common.store.docstore import DocStore


class QuickConfig(BaseModel):
    # Playtest 2026-09-27: 15 s window (points 15..1) and -6 for a wrong answer (same 40% of max as -4/10);
    # a longer reveal leaves room for the round-result celebration.
    normal_questions: int = 10
    seconds: int = 15
    reveal_ms: int = 3500
    wrong_penalty: int = -6
    no_answer_penalty: int = 0
    bot_fill_ms: int = 3000
    sudden_death_unresolved_cap: int = 5
    reserve_questions: int = 5
    round_lead_ms: int = 2000
    # The first question waits longer so the ready screen (roster + rules) can be read (playtest 2026-09-27).
    first_round_lead_ms: int = 6000
    rematch_window_ms: int = 10_000


class SurvivalConfig(BaseModel):
    seconds: int = 15
    reveal_ms: int = 3500
    bot_fill_ms: int = 5000
    unresolved_round_cap: int = 3
    rescue_seconds: int = 20
    candidate_questions: int = 30
    reserve_questions: int = 10
    round_lead_ms: int = 2000
    # The first question waits longer so the ready screen (roster + rules) can be read (playtest 2026-09-27).
    first_round_lead_ms: int = 6000
    # Opening rounds are always EASY so a full lobby is not wiped out at once (playtest 2026-09-27).
    easy_opening_rounds: int = 3
    # Weighted difficulty by active count bands (spec §4.4, eased after the playtest).
    easy_weight_8_10: float = 0.65
    easy_weight_5_7: float = 0.35
    hard_weight_3_4: float = 0.5


class MatchmakingConfig(BaseModel):
    ping_bands_ms: list[int] = Field(default_factory=lambda: [60, 120, 200])
    initial_mmr_range: int = 100
    widened_mmr_range: int = 250
    widen_after_ms: int = 1500
    ticket_ttl_ms: int = 60_000
    candidate_scan_limit: int = 50
    max_active_rooms_per_shard: int = 625
    claim_stale_ms: int = 10_000


class RankedConfig(BaseModel):
    quick_min_other_humans: int = 2
    quick_min_total_humans: int = 3
    survival_min_other_humans: int = 3
    survival_min_total_humans: int = 4
    quick_k: int = 32
    survival_k: int = 40
    provisional_matches: int = 20
    provisional_multiplier: float = 1.5
    placement_matches: int = 5
    start_mmr: int = 1000

    @model_validator(mode="after")
    def _never_weaker(self) -> RankedConfig:
        # Server config may make the human requirement stricter, never weaker (spec §7.5).
        if (self.quick_min_other_humans < 2 or self.quick_min_total_humans < 3
                or self.survival_min_other_humans < 3 or self.survival_min_total_humans < 4):
            raise ValueError("ranked human-opponent requirements cannot be weakened")
        return self


class LeagueConfig(BaseModel):
    """Weekly cohort leagues (playtest 2026-09-27, replaces MMR-threshold leagues and placement).

    Each week a player competes in a group of ``group_size`` seats of their tier; bots fill the empty seats.
    The top ``promote`` move up a tier, the bottom ``demote`` move down (never below Bronze).
    """

    group_size: int = Field(default=100, ge=10, le=200)
    promote: int = Field(default=20, ge=0)
    demote: int = Field(default=20, ge=0)
    # While fewer humans than this played ranked in the current or previous week, matches with bots count as
    # ranked so leagues and leaderboards are alive from day one.
    bootstrap_active_humans: int = Field(default=100, ge=0)
    # Weekly XP range of Bronze bots (log-uniform); each higher tier multiplies it by ``bot_xp_tier_factor``.
    bot_xp_min: int = 40
    bot_xp_max: int = 1400
    bot_xp_tier_factor: float = 1.3


class EconomyConfig(BaseModel):
    rewarded_xp_daily_cap: int = 5
    reward_offer_ttl_ms: int = 15 * 60_000
    interstitial_min_interval_s: int = 45
    # Playtest 2026-09-27: after this many completed matches the next match starts after an interstitial,
    # preceded by a short notice card. No fill, offline, missing consent or Remove Ads never blocks play.
    ad_gate_every_matches: int = Field(default=3, ge=0)
    daily_mission_xp: int = 30
    weekly_mission_xp: int = 100
    weekly_mission_count: int = 4


class BotProfileConfig(BaseModel):
    accuracy: dict[str, float]
    mmr: int
    # Response time distribution (ms) per difficulty: mean and stddev, clamped to [min, max].
    response_mean_ms: dict[str, int]
    response_sd_ms: int = 1400
    response_min_ms: int = 1300
    answer_rate: float = 0.97


def _default_bot_profiles() -> dict[str, BotProfileConfig]:
    means = {"EASY": 4200, "MEDIUM": 5600, "HARD": 6800}
    return {
        "BEGINNER": BotProfileConfig(accuracy={"EASY": 0.70, "MEDIUM": 0.45, "HARD": 0.20}, mmr=850,
                                     response_mean_ms={k: v + 900 for k, v in means.items()}, answer_rate=0.9),
        "NORMAL": BotProfileConfig(accuracy={"EASY": 0.85, "MEDIUM": 0.65, "HARD": 0.40}, mmr=1000,
                                   response_mean_ms=means),
        "STRONG": BotProfileConfig(accuracy={"EASY": 0.94, "MEDIUM": 0.80, "HARD": 0.60}, mmr=1200,
                                   response_mean_ms={k: v - 600 for k, v in means.items()}),
        "EXPERT": BotProfileConfig(accuracy={"EASY": 0.98, "MEDIUM": 0.91, "HARD": 0.78}, mmr=1450,
                                   response_mean_ms={k: v - 1100 for k, v in means.items()}, answer_rate=0.99),
    }


class BotConfig(BaseModel):
    profiles: dict[str, BotProfileConfig] = Field(default_factory=_default_bot_profiles)
    reaction_probability: float = 0.15


class FeatureConfig(BaseModel):
    survival_enabled: bool = True
    category_queues_enabled: bool = False
    # Category queues (spec §3.5, §12.3): off by default; when the master flag is on, only the categories listed
    # for a "language:region" partition are offered. Mixed stays the default queue everywhere.
    category_queue_partitions: dict[str, list[str]] = Field(default_factory=dict)
    # Rewarded bonus XP is off: XP comes only from play, so leagues stay fair (playtest 2026-09-27).
    rewarded_offers_enabled: bool = False
    competitive_languages: list[str] = Field(default_factory=lambda: ["en"])
    ui_languages: list[str] = Field(default_factory=lambda: ["en", "tr"])
    new_matches_enabled: bool = True

    def category_queues_for(self, language: str, region: str) -> list[str]:
        if not self.category_queues_enabled:
            return []
        return list(self.category_queue_partitions.get(f"{language}:{region}", []))


class ModerationConfig(BaseModel):
    question_quarantine_min_reporters: int = 10
    question_quarantine_rate: float = 0.02
    question_report_period_ms: int = 30 * 86_400_000
    # Anti-cheat risk score (spec §28.4): graduated, temporary restrictions; never an automatic ban.
    risk_fast_correct_ms: int = Field(default=300, ge=100, le=2000)
    risk_fast_correct_min_rounds: int = Field(default=3, ge=1)
    risk_half_life_days: float = Field(default=14.0, gt=0)
    risk_review_score: float = 25.0
    risk_ranked_restrict_score: float = 40.0
    risk_ranked_restrict_ms: int = 7 * 86_400_000
    risk_queue_restrict_score: float = 80.0
    risk_queue_restrict_ms: int = 86_400_000
    # Account-creation abuse: distinct accounts seen on one device within the window.
    risk_accounts_per_device: int = Field(default=3, ge=1)
    risk_device_window_ms: int = 30 * 86_400_000


class ContentConfig(BaseModel):
    # Versioned near-duplicate threshold for semantic similarity (spec §11.2).
    near_duplicate_threshold: float = Field(default=0.86, ge=0.5, le=1.0)
    ai_min_global_relevance: int = Field(default=4, ge=1, le=5)
    ai_max_candidates_per_job: int = Field(default=25, ge=1, le=100)
    # Empirical difficulty (spec §3.4, §10.3): never before 200 valid human attempts per language/mode/version.
    empirical_min_attempts: int = Field(default=200, ge=200)
    empirical_easy_min_accuracy: float = Field(default=0.70, gt=0, lt=1)
    empirical_medium_min_accuracy: float = Field(default=0.40, gt=0, lt=1)


class RetentionConfig(BaseModel):
    live_cleanup_after_settlement_ms: int = 30 * 60_000
    settlement_max_retries: int = 8


class GameConfig(BaseModel):
    schema_version: int = 1
    config_version: int = 1
    quick: QuickConfig = Field(default_factory=QuickConfig)
    survival: SurvivalConfig = Field(default_factory=SurvivalConfig)
    matchmaking: MatchmakingConfig = Field(default_factory=MatchmakingConfig)
    ranked: RankedConfig = Field(default_factory=RankedConfig)
    leagues: LeagueConfig = Field(default_factory=LeagueConfig)
    economy: EconomyConfig = Field(default_factory=EconomyConfig)
    bots: BotConfig = Field(default_factory=BotConfig)
    features: FeatureConfig = Field(default_factory=FeatureConfig)
    moderation: ModerationConfig = Field(default_factory=ModerationConfig)
    content: ContentConfig = Field(default_factory=ContentConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)

    def match_snapshot(self, mode: str) -> dict[str, Any]:
        section = self.quick if mode == "QUICK" else self.survival
        return {
            "config_version": self.config_version,
            "mode": section.model_dump(),
            "ranked": self.ranked.model_dump(),
            "leagues": self.leagues.model_dump(),
        }


class ServerConfigService:
    ACTIVE_PATH = "server_config/active"

    def __init__(self, store: DocStore, cache_ttl_s: float = 5.0) -> None:
        self._store = store
        self._ttl = cache_ttl_s
        self._cached: GameConfig | None = None
        self._checked_at = 0.0

    async def get(self) -> GameConfig:
        if self._cached is not None and time.monotonic() - self._checked_at < self._ttl:
            return self._cached
        pointer = await self._store.get(self.ACTIVE_PATH)
        version = pointer["config_version"] if pointer else None
        if self._cached is None or version != self._cached.config_version:
            if version is None:
                self._cached = GameConfig()
            else:
                doc = await self._store.get(f"server_config/v{version}")
                self._cached = GameConfig.model_validate(doc) if doc else GameConfig()
        self._checked_at = time.monotonic()
        return self._cached

    async def publish(self, config: GameConfig, actor_uid: str, now_ms: int) -> GameConfig:
        """Store a new immutable config version and activate it (admin only)."""
        current = await self.get()
        new = GameConfig.model_validate({**config.model_dump(), "config_version": current.config_version + 1})
        await self._store.create(f"server_config/v{new.config_version}",
                                 {**new.model_dump(), "published_by": actor_uid, "published_at_ms": now_ms})
        await self._store.set(self.ACTIVE_PATH, {"config_version": new.config_version, "updated_at_ms": now_ms})
        self._cached = None
        return new

    def invalidate(self) -> None:
        self._cached = None
