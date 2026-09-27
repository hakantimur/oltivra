"""Locust load test (spec §40.7): real match lifecycles, not smooth HTTP traffic.

Run the API against the emulator suite with fake auth (never against production):

    OLTIVRA_AUTH_MODE=fake OLTIVRA_APP_CHECK_MODE=off OLTIVRA_STORE_BACKEND=firebase \
        uvicorn app.main:app_from_env --factory --port 8000
    locust -f load/locustfile.py --host http://127.0.0.1:8000

Staged ramp (100 -> 1,000 -> 5,000 -> 10,000 -> burst) with ``LOAD_SHAPE=stages``.

Workloads (user classes, weighted):
- QuickPlayer / SurvivalPlayer: dense Quick Battle and Survival with mixed latency bands and MMR spread.
- BoundaryBurstPlayer: synchronised answers within ~60 ms of ``ends_at_ms`` (scoring-boundary races).
- SyncFallbackPlayer: no realtime listener; drives progress through ``/sync`` bursts (RTDB loss/reconnect).
- ChaosOperator: duplicate/late recovery via maintenance sweeps (Cloud Tasks delay/duplicate injection).

Custom metrics: ``match/finished`` (duration of a whole match) and ``match/answer_rejected`` (per error code).
"""

from __future__ import annotations

import os
import random
import time
import uuid

from locust import HttpUser, LoadTestShape, between, events, task

TERMS_VERSION = PRIVACY_VERSION = "2026-09"
INTERNAL_SECRET = os.environ.get("OLTIVRA_INTERNAL_SHARED_SECRET", "dev-internal-secret")
RTT_BANDS = [(15, 60), (61, 120), (121, 200), (201, 320)]
AVATARS = [f"av_{i:03d}" for i in range(1, 13)]
MATCH_TIMEOUT_S = {"quick": 8 * 60, "survival": 30 * 60}


def rid() -> str:
    return str(uuid.uuid4())


def fire(name: str, started: float, exc: Exception | None = None, length: int = 0) -> None:
    events.request.fire(request_type="match", name=name, response_time=(time.perf_counter() - started) * 1000,
                        response_length=length, exception=exc, context={})


class Player(HttpUser):
    abstract = True
    wait_time = between(1, 4)
    mode = "quick"
    # Human-like answer delay after the question becomes answerable, in seconds.
    think = (1.2, 7.0)
    listener = True  # False = no RTDB listener: rely on /sync (fallback storm)

    def on_start(self) -> None:
        self.uid = f"load-{uuid.uuid4().hex[:20]}"
        self.headers = {"authorization": f"Bearer test:{self.uid}"}
        self.rtt = random.randint(*random.choice(RTT_BANDS))
        self.clock_offset_ms = 0
        self._post("/v1/onboarding/consent", {"age_gate_confirmed": True, "terms_version": TERMS_VERSION,
                                              "privacy_version": PRIVACY_VERSION}, name="onboarding/consent")
        username = f"ld{uuid.uuid4().hex[:12]}"
        self._post("/v1/profile/username", {"username": username}, name="profile/username")
        self._request("PATCH", "/v1/profile/avatar", {"avatar_id": random.choice(AVATARS)}, name="profile/avatar")

    # ------------------------------------------------------------------------------------------ http helpers
    def _request(self, method: str, path: str, body: dict | None = None, name: str | None = None,
                 expect: tuple[int, ...] = (200,)):
        payload = None
        headers = dict(self.headers)
        if method != "GET":
            key = rid()
            payload = {"request_id": key, **(body or {})}
            headers["x-idempotency-key"] = key
        with self.client.request(method, path, json=payload, headers=headers, name=name or path,
                                 catch_response=True) as res:
            if res.status_code in expect:
                res.success()
            elif res.status_code in (409, 429) or res.status_code == 400 and "ROUND" in res.text:
                res.success()  # expected races under load; tracked separately
            else:
                res.failure(f"{res.status_code}: {res.text[:160]}")
            return res

    def _post(self, path: str, body: dict | None = None, name: str | None = None):
        return self._request("POST", path, body, name)

    def server_now(self) -> int:
        return int(time.time() * 1000) + self.clock_offset_ms

    # ------------------------------------------------------------------------------------------ match flow
    @task
    def play_match(self) -> None:
        started = time.perf_counter()
        res = self._post(f"/v1/matchmaking/{self.mode}/join", {"median_rtt_ms": self.rtt},
                         name=f"matchmaking/{self.mode}/join")
        if res.status_code != 200:
            return
        match_id = self._wait_for_match()
        if not match_id:
            self._request("DELETE", f"/v1/matchmaking/{self.mode}/leave", name=f"matchmaking/{self.mode}/leave")
            return
        finished = self._play(match_id)
        fire(f"{self.mode}/finished", started, None if finished else TimeoutError("match did not finish"))

    def _wait_for_match(self) -> str | None:
        deadline = time.time() + 60
        while time.time() < deadline:
            status = self._request("GET", "/v1/matchmaking/status", name="matchmaking/status").json()
            if status.get("state") == "MATCHED":
                return status["match"]["match_id"]
            if status.get("state") not in ("QUEUED", "MATCHING"):
                return None
            time.sleep(1.0)
        return None

    def _play(self, match_id: str) -> bool:
        answered: set[str] = set()
        deadline = time.time() + MATCH_TIMEOUT_S[self.mode]
        while time.time() < deadline:
            view = self._request("GET", f"/v1/matches/{match_id}", name="matches/view").json()
            if "server_time_ms" in view:
                self.clock_offset_ms = int(view["server_time_ms"] - time.time() * 1000)
            public = view.get("public") or {}
            private = view.get("player_private") or {}
            state = public.get("state")
            if state in ("FINISHED", "CANCELLED") or view.get("index_state") in ("FINISHED", "CANCELLED"):
                return True
            round_id = private.get("round_id")
            if state in ("ROUND_LOADING", "ROUND_ACTIVE") and private.get("eligible_to_answer") \
                    and round_id and round_id not in answered:
                self._answer(match_id, view, public, private)
                answered.add(round_id)
            if not self.listener or self.server_now() > int(public.get("next_server_event_at_ms") or 0) + 500:
                self._post(f"/v1/matches/{match_id}/sync",
                           {"observed_state_version": int(public.get("state_version") or 0)}, name="matches/sync")
            if random.random() < 0.05:  # sparse reactions (one per round is enforced server-side)
                self._post(f"/v1/matches/{match_id}/reaction", {"round_id": round_id or "",
                                                                "reaction_id": "emoji_clap"}, name="matches/reaction")
            time.sleep(0.25 if not self.listener else 0.8)
        return False

    def _answer_at(self, public: dict) -> float:
        starts = int(public.get("starts_at_ms") or self.server_now())
        return starts + random.uniform(*self.think) * 1000

    def _answer(self, match_id: str, view: dict, public: dict, private: dict) -> None:
        target = min(self._answer_at(public), int(public.get("ends_at_ms") or 0) - 20)
        delay = (target - self.server_now()) / 1000
        if delay > 0:
            time.sleep(min(delay, 20))
        options = list((private.get("option_order") or {}).values())
        if not options:
            return
        started = time.perf_counter()
        res = self._post(f"/v1/matches/{match_id}/answer", {"round_id": private["round_id"],
                                                             "option_id": random.choice(options),
                                                             "rtdb_shard_id": view.get("rtdb_shard_id")},
                         name="matches/answer")
        if res.status_code != 200:
            code = (res.json().get("error") or {}).get("code", str(res.status_code)) if res.text else "EMPTY"
            fire(f"answer_rejected/{code}", started)


class QuickPlayer(Player):
    weight = 6
    mode = "quick"


class SurvivalPlayer(Player):
    weight = 3
    mode = "survival"
    think = (2.0, 10.0)


class BoundaryBurstPlayer(Player):
    """Answers land together just before the round closes: exercises ordering at scoring boundaries."""

    weight = 1
    mode = "quick"

    def _answer_at(self, public: dict) -> float:
        return int(public.get("ends_at_ms") or self.server_now()) - random.uniform(10, 60)


class SyncFallbackPlayer(Player):
    """Behaves like a client whose RTDB listener dropped: progress only through /sync and snapshots."""

    weight = 1
    listener = False


class ChaosOperator(HttpUser):
    """Injects duplicate/late recovery work the way Cloud Scheduler and redelivered tasks would."""

    fixed_count = 1
    wait_time = between(5, 10)
    headers = {"x-internal-auth": INTERNAL_SECRET}

    @task(3)
    def sweep_stale_matches(self) -> None:
        self.client.post("/internal/maintenance/sweep-stale-matches", headers=self.headers,
                         name="internal/sweep-stale-matches")

    @task(1)
    def expire_tickets(self) -> None:
        self.client.post("/internal/maintenance/expire-tickets", headers=self.headers,
                         name="internal/expire-tickets")


class StagedShape(LoadTestShape):
    """100 -> 1,000 -> 5,000 -> 10,000 concurrent humans, then a burst above target (spec §40.7)."""

    use_common_options = True
    stages = [(180, 100, 10), (480, 1_000, 25), (900, 5_000, 50), (1_500, 10_000, 100), (1_680, 12_500, 250),
              (1_800, 1_000, 250)]

    def tick(self):
        if os.environ.get("LOAD_SHAPE") != "stages":
            return None
        run_time = self.get_run_time()
        for until, users, rate in self.stages:
            if run_time < until:
                return users, rate
        return None


if os.environ.get("LOAD_SHAPE") != "stages":
    del StagedShape  # locust picks up any LoadTestShape subclass; keep manual control by default
