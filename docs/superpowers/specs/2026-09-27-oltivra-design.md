# Oltivra — Implementation Design

**Authoritative product spec:** `docs/spec/synova_live_trivia_development_spec_v1_1.md` (called "the spec").
**Visual design:** `docs/design/` (Stitch packages 00–08, 48 screens; `DESIGN.md` tokens).
This document records *how* we implement the spec in this repository, and every decision where the
spec leaves latitude or where the product owner overrode it.

## 1. Product-owner decisions (2026-09-27)

| # | Decision | Effect |
|---|---|---|
| D1 | Mobile client in **Flutter** (Riverpod + go_router) as in spec §13.1 | `mobile/`; tested locally via Flutter web + widget tests |
| D2 | **Local-only** runtime: Firebase Emulator Suite (Docker) | Deploy artefacts (Dockerfile, cloudbuild, rules, queue yaml) exist but are not deployed |
| D3 | **Bots are not labelled** in the UI (design packages override spec §23.1 badge rule) | Public projection never carries `is_bot`; disclosure remains in Terms/Help text (spec §23.1 bullet 3) |
| D4 | Git flow: feature branch → PR → `Hakan-oltivra`; batch PR `Hakan-oltivra` → `main` every 7–8 PRs and before a new phase | GitHub Actions run only on `main` PRs/pushes |

## 2. Spec gaps resolved here

- **Mission reward:** claiming a completed mission grants a configured lifetime-XP amount (default 30 daily / 100 weekly). It never affects ranked weekly XP, MMR or league (consistent with §7.2 philosophy).
- **League display:** spec leagues have no divisions; the Stitch "Silver II" treatment becomes "Silver" plus a progress bar toward the next threshold (no raw MMR, §7.3).
- **Home "This week":** shows weekly rank + ranked weekly XP; the Stitch "3-day streak" card becomes the Quick Battle ranked win streak.
- **Brand text:** app name "Oltivra"; the deletion screen names the shared account ("Synova account") per §2.2.
- **Seed content:** the language activation gate (§12.2, 6,000 groups) cannot be met by a seed. We ship ~360 verified English seed groups (40 per category, balanced difficulty) with Turkish translations, and the manifest/gate tooling reports the gate as *not met*; `competitive_language_gate` in server config is overridable only in `dev`.
- **Rematch record:** stored in Firestore `rematches/{rematch_id}` (spec lists endpoints only).
- **Distributed rate limit / idempotency:** Firestore documents `rate_limits/{key}` and `idempotency_records/{hash}` (TTL fields), satisfying §28.3 "server-owned and distributed".

## 3. Repository layout

```
backend/            FastAPI service (Python 3.12, Pydantic v2)
  app/<module>/      one package per spec §19 module
  tests/unit         pure logic + in-memory store tests (fast, no Docker)
  tests/integration  emulator-backed tests (Docker)
mobile/             Flutter app
admin/              Next.js internal admin
firebase/           firestore.rules, firestore.indexes.json, rtdb/live-shard.rules.json,
                    storage.rules, rules tests (Node), emulator Dockerfile
infra/              cloudbuild.yaml, cloudrun.yaml, cloudarmor.yaml, cloudtasks.yaml
loadtest/           Locust scenarios (§40.7)
scripts/            seed, manifest build, dev helpers
firebase.json, docker-compose.yml
```

## 4. Backend architecture

### 4.1 Ports and adapters
Game correctness must be testable without cloud services, so every external dependency is a port:

| Port | Production adapter | Local/test adapter |
|---|---|---|
| `DocStore` (Firestore semantics: get/set/update/delete/query/transaction) | `FirestoreDocStore` (firebase-admin, run in bounded thread pool) | `MemoryDocStore` |
| `LiveStore` (RTDB shard ring: get/set/delete/transaction on a path) | `RtdbLiveStore` (one firebase-admin app per shard URL) | `MemoryLiveStore` |
| `TaskScheduler` (Cloud Tasks) | `CloudTasksScheduler` | `LocalTaskScheduler` (asyncio timers → internal handler) / `RecordingScheduler` |
| `TokenVerifier` / `AppCheckVerifier` | firebase-admin | `FakeTokenVerifier` (`test:<uid>`; refused when `ENV=prod`) |
| `MediaSigner` | GCS V4 signed URL (local crypto, no network) | emulator URL |
| `Clock` | system ms | `FakeClock` |
| Store verifiers, AdMob SSV keys, AI provider, embeddings | Google Play API, Apple JWS chain, gstatic keys, Anthropic | deterministic fakes |

The same service code runs against both. `APP_STORE_BACKEND=memory|firebase`.

### 4.2 Live match engine (pure)
The canonical RTDB match root (§17) is a plain dict. All rules are pure functions
`(state, now_ms, input) -> state'` with no I/O, called inside the RTDB root transaction:

- `matches/engine.py` — `resolve_due`, `apply_answer`, `apply_reaction`, `apply_leave`, projections.
- `quick_battle/rules.py` — scoring (§3.2), ranking (§3.7), sudden death (§3.8).
- `survival/rules.py` — resolution, rescue, tiebreak (§4.2–4.5).
- `bots/planner.py` — HMAC-seeded precommitted plans (§23.3).

The whole question plan (texts, options, correct concept, media refs) is copied into
`authoritative/` at PREPARING, so round creation needs no network call inside the transaction.
Effects (tasks to schedule, settlement to start) are returned from the pure step and executed after commit.

### 4.3 Flows
- Matchmaking (§21): Firestore ticket + `user_runtime` transaction; roster claim transaction; bot fill when the caller polls at `human_fill_at_ms`.
- Rounds (§20): ROUND_START, ROUND_RECOVERY, BOT_WINNER, ROUND_ADVANCE tasks all call `resolve_round_if_due`; answer and sync endpoints reconcile first.
- Settlement (§37): ledger → idempotent Firestore transaction per match → runtime IDLE → public FINISHED → cleanup task.

## 5. Mobile architecture
Spec §39 layout. Design tokens from `DESIGN.md` → `shared/theme`. Plus Jakarta Sans via bundled font.
English and Turkish ARB localisation from the first commit. The live match screen subscribes to
`public/` and `player_private/{uid}` of the assigned shard only (§14.1).

## 6. Testing
- Unit (pytest): every §40 scoring/Quick/Survival/bot/matchmaking case against memory adapters.
- Integration: FastAPI TestClient end-to-end with memory adapters; emulator suite for Firestore/RTDB adapters.
- Security rules: `@firebase/rules-unit-testing` against the emulator (§40.6).
- Mobile: widget tests per screen + Flutter web smoke run in the browser.
- Load: Locust scenarios checked in; run locally at 100-client scale only.

## 7. Delivery plan (PRs into `Hakan-oltivra`)

Batch 1 — backend: B0 foundation · B1 question platform · B2 accounts/safety · B3 matchmaking + live substrate ·
B4 Quick Battle + bots · B5 Survival · B6 settlement, progression, social · B7 monetization + admin/moderation API + load tests → **merge to main**.

Batch 2 — clients: F1 onboarding · F2 home/play/matchmaking · F3 Quick Battle · F4 Survival · F5 social ·
F6 progress/profile · F7 settings/safety · F8 monetization/reliability · A1 admin web → **merge to main**.
