# Oltivra Implementation Plan

> **For agentic workers:** executed inline (superpowers:executing-plans). Steps use checkbox syntax.

**Goal:** Implement the Oltivra live trivia backend, Flutter client (all 48 designed screens) and admin web exactly per the spec.

**Architecture:** One FastAPI service with ports/adapters (memory + Firebase), pure match engine run inside RTDB root transactions, Flutter client rendering public/private projections. See design doc.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, firebase-admin, pytest; Flutter 3.47, Riverpod, go_router, firebase_* SDKs; Next.js; Firebase Emulator Suite in Docker.

**Spec:** `docs/spec/synova_live_trivia_development_spec_v1_1.md`, `docs/superpowers/specs/2026-09-27-oltivra-design.md`

## Global Constraints

- Client is never authoritative (§0.1.1); no answer key / future question / bot plan reaches a client (§0.1.2–3).
- All state-changing APIs idempotent with `request_id` + `X-Idempotency-Key` (§19.1); error envelope §19.2.
- Timestamps are integer UTC ms. `points = clamp(floor((ends_at_ms - received_at_ms)/1000), 1, 10)`; timely iff `received < ends_at`.
- Quick: 4 slots, 10 questions, 11 000 ms, wrong −4, no answer 0, reveal 2 500 ms, sudden-death cap 5.
- Survival: 10 slots, 11 000 ms, reveal 3 000 ms, rescue 15 000 ms Easy, unresolved cap 3.
- Every persistent doc and wire payload carries `schema_version`.
- UI strings localisation-ready (ARB en + tr). Public UI never distinguishes bots (D3).
- No TODO placeholders in security, scoring, state-machine, payment, deletion or moderation code.

## Task list

### B0 Foundation — PR 1
- [ ] Monorepo skeleton, `.gitignore`, README, `firebase.json`, emulator Dockerfile + `docker-compose.yml`
- [ ] `common/`: settings, error contract + codes, clock, ids, HMAC keyring, structured logging (no secrets), request-id middleware
- [ ] Ports: `DocStore`, `LiveStore`, `TaskScheduler` + memory adapters + Firebase adapters
- [ ] `auth/`: ID token + App Check verification dependency, account-state check, internal task auth (OIDC / shared secret locally)
- [ ] Idempotency service (48 h), distributed rate limiter
- [ ] `GET /v1/ping`, `GET /healthz`
- [ ] Firestore/RTDB/Storage rules baseline (default deny) + rules tests
- [ ] GitHub Actions (main only): backend pytest + ruff
- Tests: error envelope, idempotency replay/409, rate limit window, fake auth refused in prod, memory store transaction conflict.

### B1 Question platform — PR 2
- [ ] Models: categories (exactly 9), subcategories, question group, translation, private answer, media asset
- [ ] Competitive eligibility predicate (§9.3, §26.3) and text-length validation (§9)
- [ ] Manifest builder (§12.1) + in-memory cache with version check; no answer keys in manifest
- [ ] Exposure service: recent 2 500 unique qids, fallback ladder 2500/1000/300/LRU (§10.2)
- [ ] Question selector: Quick 10 + 5 reserve with difficulty order & category diversity (§3.4–3.5); Survival 30 + 10 (§26.2)
- [ ] Seed content (~360 groups, en + tr) + seed script; `GET /v1/categories`; language gate report
- Tests: eligibility filters, diversity max 2/category & no consecutive subcategory, fallback ladder, manifest contains no answer.

### B2 Accounts, profile, safety — PR 3
- [ ] Onboarding consent record (age gate, terms/privacy versions) — no DOB
- [ ] Username rules, reserved/profanity list, atomic registry, 30-day cooldown + 30-day reservation
- [ ] Avatar & reaction catalogs; `POST /v1/session/bootstrap`, `GET /v1/profile`, username/avatar endpoints, `GET /v1/client-config`
- [ ] `user_runtime` lock state machine
- [ ] Blocks, player reports (reasons §29), rate limits
- [ ] Account deletion flow (§30.1) incl. anonymisation + reservation hash
- Tests: concurrent username race, reserved names, cooldown, runtime conflicts, deletion with active match.

### B3 Matchmaking + live substrate — PR 4
- [ ] Shard ring (HMAC → live-NN), match index
- [ ] Ping bands; tickets join/leave/status; formation + roster claim; widening; bot fill; expiry; block exclusion; admission control
- [ ] Match root creation (PREPARING → ROUND_LOADING), projections, resolver entry `resolve_round_if_due`, sync endpoint with designated resolver, task handlers
- [ ] `GET /v1/matches/{id}`, `/sync`, `/leave`
- Tests: double-match across concurrent joins, duplicate/delayed task no-op, bot fill at deadline, block race, second queue refused.

### B4 Quick Battle + bots — PR 5
- [ ] Bot profiles, planner (accuracy matrix, response distribution, HMAC seed, commit hash)
- [ ] Quick rules: answer, wrong lock −4, winner, reveal, next round, ranking, sudden death + cap, abandonment
- [ ] Answer endpoint + reactions (catalog, one per round, block hiding)
- [ ] Question report endpoint + auto quarantine rule
- Tests: all §40.1 / §40.2 / §40.5 cases.

### B5 Survival — PR 6
- [ ] Hidden answers, resolution, all-wrong protection, zero-answer rescue, 3-unresolved tiebreak, deterministic ordering, placements bands, spectators, background reserve refill
- Tests: all §40.3 cases.

### B6 Settlement, progression, social — PR 7
- [ ] Settlement ledger + transaction: history, XP, level, ranked eligibility, MMR/league/placement, streak/crowns, weekly stats, missions, badges, category stats, exposure append, question stat shards, progression events
- [ ] Missions daily/weekly + claim; leaderboard; league; category stats endpoints
- [ ] Friends, search, requests; parties/challenges; rematch
- Tests: idempotent settlement, bot-heavy not ranked, Elo math, level curve, rematch after exposure commit.

### B7 Monetization, admin, moderation, load — PR 8
- [ ] Reward offers + AdMob SSV verification; daily cap; bonus excludes ranked
- [ ] Google/Apple verification, entitlements, RTDN/ASN handlers, restore
- [ ] Admin API (all §11 areas) with admin claim + MFA; audit log; sanctions; AI generation jobs; duplicate detection; pool health
- [ ] Locust load scenarios; infra yaml
- Tests: SSV signature/nonce/duplicate, purchase pending/refund, admin authz.

→ Merge `Hakan-oltivra` → `main` (batch 1).

### F1–F8, A1 — PRs 9–17
One PR per Stitch package (6 screens each), then admin web. Each: screens match `docs/design/<screen>/screen.png`, wired to backend, widget tests, web smoke run.

→ Merge `Hakan-oltivra` → `main` (batch 2).
