# SYNOVA SHARED QUESTION PLATFORM + LIVE TRIVIA GAME
## Production Product & Engineering Specification — v1.1

**Status:** Authoritative implementation specification  
**Audience:** Claude / engineering team  
**Primary language:** English  
**Target age:** 13+  
**Soft-launch operating cap:** 1,000 simultaneous authenticated human players  
**Production design target:** 10,000 simultaneous authenticated human players  
**Product principle:** The system must be simple enough for a two-person team to operate, while every competitive outcome remains server-authoritative, auditable, fair within the defined latency policy, and recoverable after retries or temporary failures.

This document supersedes earlier Synova Live Trivia specifications. It is intentionally explicit where an implementation choice changes game fairness, security, data consistency, capacity, legal compliance, or monetization. Claude must implement it as written. A genuine technical impossibility must be documented before changing a locked rule.

---

# 0. EXECUTION RULES

## 0.1 Non-negotiable implementation rules

1. The mobile client is a renderer and input device. It is never authoritative for score, elapsed time, winner, correct answer, bot action, MMR, XP, league, entitlement, mission completion, or match state.
2. Never expose a future question, its options, its image URL, its correct answer, a bot plan, or a private match field to a client before that round begins.
3. Never place answer keys, backend secrets, service credentials, signing keys, server-only configuration, or bot plans in Flutter code, Firebase Remote Config, Analytics, or client-readable Firestore/RTDB paths.
4. All state-changing APIs are idempotent. A retry must return the original outcome or a safe conflict result; it must not create a second outcome.
5. Every authoritative state transition is serialised by a server-side transaction on the canonical live match root.
6. All user-visible strings are localisation-ready from the first commit.
7. All persistent documents and wire payloads carry an explicit schema version where migration is plausible.
8. Use Firebase Emulator Suite for local integration testing. Use real stage services for load, App Check, RTDB-shard, purchase, and ad verification tests.
9. Use test AdMob IDs and sandbox/store-test IAP outside production.
10. Add unit, integration, security-rule, and failure tests with each feature. Do not defer security-critical tests.
11. Do not leave TODO placeholders in security, scoring, state-machine, payment, deletion, or moderation flows.
12. Prefer the simplest design that preserves correctness at the stated scale. Do not introduce Kubernetes, EKS, Kafka, RabbitMQ, Redis clusters, custom WebSocket infrastructure, GraphQL, or microservice sprawl unless a measured bottleneck later requires it.
13. Firebase Realtime Database sharding is an approved native Firebase scaling mechanism for live match traffic. It is not an optional future redesign.
14. Cloud Tasks is a durable, at-least-once wake-up and recovery mechanism. It is not an exact real-time clock.
15. A production release may not claim support for 10,000 simultaneous human players until the exact 10,000-human load scenarios in this document pass in the production-like stage environment.

## 0.2 Definitions

| Term | Meaning |
|---|---|
| **Human player** | One authenticated client connection controlled by a real user. Bots never count as human players or client connections. |
| **Slot** | One position in a match roster. A slot can be human or bot. |
| **Active room** | A room in WAITING_FOR_PLAYERS, PREPARING, or any playable round state. |
| **Canonical live state** | The complete server-only-plus-public match object stored in one RTDB match root on one assigned RTDB shard. |
| **Public projection** | The client-readable subset of a canonical live state. |
| **Player-private projection** | The subset readable only by one participant, such as that participant’s option order. |
| **Authoritative order** | The serial commit order of the canonical RTDB match-root transaction. Client clocks and client sequence numbers never determine it. |
| **Ranked-eligible match** | A completed match satisfying the minimum human-opponent rule in Section 7.5. It may change MMR, ranked weekly XP, and win streak. |
| **Base match XP** | XP calculated from game performance before any rewarded-ad multiplier. |
| **Reward bonus XP** | Extra XP granted after a server-verified rewarded-ad callback. It affects lifetime XP only, not ranked weekly XP, MMR, placement, streak, or mission counters. |
| **Question group** | One conceptual fact/question shared across translations and across Synova products. |
| **Question version** | Immutable content version used in a particular match. Editing a question creates a new version; history is never silently rewritten. |
| **Round resolver** | The single idempotent server function that reconciles due bot actions, expires a round, calculates outcome, and moves the state machine forward. |

## 0.3 Locked capacity model

The production target is **10,000 simultaneous authenticated human players**, not 10,000 total roster slots. Capacity calculations must always include the following three scenarios:

1. **Dense-human scenario:** 10,000 humans in mostly full rooms.
2. **Mixed-liquidity scenario:** 10,000 humans distributed across languages, MMR bands, and bot-fill rates observed in soft launch.
3. **Worst bot-fill scenario:** 10,000 humans each enter a room that contains the minimum number of humans and the maximum permitted number of bots.

The worst bot-fill scenario can create far more active rooms than the dense-human scenario. It is therefore a required load-test case, not a theoretical edge case.

---

# 1. PRODUCT SUMMARY

We are building a standalone live multiplayer trivia game that consumes the same centrally prepared question platform as Synova.

The shared question platform is the durable product asset. Questions are created once, verified once, translated once, licensed once, versioned once, and reused by:

- Synova curiosity / solo question experiences.
- Synova Live Trivia.
- Future Synova quiz products.

The Live Trivia product has two primary modes:

- **Quick Battle:** Four-slot competitive first-authoritative-correct-answer scoring.
- **Survival:** Ten-slot elimination trivia where incorrect or absent answers normally eliminate players until one winner remains.

The public social layer is deliberately controlled:

- Unique username.
- Curated avatar.
- Friends, challenges, rematches, block, and report.
- Curated reactions only.
- No free-text chat, voice chat, user-uploaded avatar, or user-generated trivia at launch.

Retention systems:

- XP and levels.
- MMR and leagues.
- Weekly ranked leaderboard.
- Win streak and Survival crowns.
- Daily and weekly missions.
- Badges, frames, and category status.

Monetization:

- At most one interstitial opportunity per completed ad-supported match, subject to a 45-second minimum interval.
- Optional server-verified rewarded video for 2x base match XP, subject to daily cap.
- One-time **Remove Ads Forever** non-consumable purchase, base price USD 4.99.
- No paid score, MMR, revive, answer aid, life, or competitive power-up.

## 1.1 Architecture summary

~~~text
Synova Flutter app                 Live Trivia Flutter app
        \                              /
         \                            /
          Firebase Auth + Firebase App Check
                          |
                    FastAPI / Cloud Run
                          |
       +------------------+-------------------+
       |                  |                   |
   Firestore       RTDB match-shard ring   Cloud Storage
 persistent data     hot live state         versioned WebP
 questions/users     public/private state    private question media
 queues/history      presence/events         signed current-round delivery
       |
 Cloud Tasks (recovery / due-event wake-ups)

Plus: Firebase Analytics, Crashlytics, FCM, Remote Config,
      Secret Manager, Cloud Monitoring, Cloud Logging,
      Cloud Scheduler, AdMob, Google Play Billing, StoreKit.
~~~

**Firestore** stores durable product data, question content, queue tickets, party metadata, user progression, and match history.  
**The RTDB match-shard ring** stores only ephemeral live match state and short-lived presence.  
**Cloud Run** is the single authoritative backend codebase.  
**Cloud Tasks** wakes idempotent resolvers and retries recovery work; it never defines fairness by its delivery timestamp.  
**Cloud Storage** holds versioned WebP assets. Question media are delivered only for the current round through short-lived signed URLs.

---

# 2. LOCKED PRODUCT DECISIONS

## 2.1 Audience and age gate

- The application is **13+**.
- It must not be marketed as child-directed.
- Registration requires a 13+ declaration before account creation.
- Do not permanently store exact date of birth solely for this gate.
- Store only:

~~~text
age_gate_passed = true
age_gate_verified_at
terms_version
terms_accepted_at
privacy_version
privacy_accepted_at
~~~

- Release-market legal review remains required before launch. The 13+ declaration is not a substitute for market-specific obligations.

## 2.2 Global account scope

Synova and Live Trivia share one Firebase Auth project and one global user identity.

- A UID is global across participating Synova products.
- Question-exposure history is global across participating Synova products.
- Live Trivia progression remains product-specific and is not merged into legacy Synova progression.
- Account deletion is global. A user deleting the account from Live Trivia must be clearly told that the shared Synova account and its associated personal data across participating products will be deleted or anonymised according to the central deletion policy.
- A product must never silently delete only one app’s Firebase Auth identity while leaving another app dependent on that UID.

## 2.3 Username and avatar

Every player chooses one unique global username.

Username rules:

- 3–16 characters.
- ASCII letters A-Z, a-z, digits 0-9, underscore (_) only.
- No spaces.
- Case-insensitive uniqueness.
- Store **username_display** and lowercased **username_normalized**.
- Reject reserved product, company, system, moderation, staff, impersonation, profanity, and slur names.
- One username belongs to one UID at a time.
- Username change cooldown: 30 days.
- After a change or deletion, retain the previous normalized username in a reservation record for 30 days before release.
- Reservation is an atomic server-side transaction on username_registry/{username_normalized}.

Avatars:

- Curated catalog only in v1.
- No user-uploaded photos.
- Frames and badges are cosmetic only.
- Avatar IDs are server-validated against an active catalog.

## 2.4 Language

- Each match has exactly one **question_language** using a BCP-47 language tag.
- All players in that match receive the same verified wording and answer texts.
- Matchmaking is language-scoped.
- A missing or unverified translation never falls back silently to another language in competitive play.
- UI language and question language are separate preferences.
- Initial soft-launch competitive language is configured server-side. The default is **en**; additional languages remain disabled until they meet the activation gate in Section 12.7.

---

# 3. GAME MODE 1 — QUICK BATTLE

## 3.1 Core rules

- Four roster slots.
- Slots may be human or bot.
- Ten normal questions.
- Each normal question has an 11.0-second answer window.
- A player may submit at most one answer per round.
- An incorrect human answer immediately locks that player for the round and applies **-4** score.
- A player who does not answer receives **0**.
- The first **authoritatively accepted** correct answer wins that question.
- Once a winner is committed, the round closes immediately, the correct answer is revealed, and no further answers are accepted.
- An answer is authoritative only after the backend validates participant, state, round, option, idempotency, deadline, and transaction order.

The difference between no answer and wrong answer is intentional: Quick Battle is a confidence-and-speed game. A player may choose not to guess. UI must state this rule clearly. The server config contains **quick_no_answer_penalty = 0**; changing it later requires an explicit product decision and A/B test.

## 3.2 Timing and point formula

Canonical timestamps are integer UTC milliseconds.

~~~text
round_duration_ms = 11_000
points = clamp(
  floor((ends_at_ms - authoritative_answer_received_at_ms) / 1000),
  1,
  10
)
~~~

Examples:

~~~text
10.9 seconds remaining -> +10
10.0 seconds remaining -> +10
 9.9 seconds remaining ->  +9
 8.3 seconds remaining ->  +8
 1.2 seconds remaining ->  +1
 0.1 seconds remaining ->  +1
~~~

The backend records **authoritative_answer_received_at_ms** immediately before entering the canonical match transaction. When concurrent answers compete, the transaction commit order is the definitive winner order. No client-time or client-latency compensation is used.

An answer is timely only when authoritative_answer_received_at_ms is strictly less than ends_at_ms.

## 3.3 Wrong answer and public event

For a valid wrong human answer:

~~~text
score_delta = -4
round_locked = true
public_event = "<username> missed this one  -4"
~~~

The selected wrong option is never public.

For a correct winner:

~~~text
public_event = "<username> wins  +<points>"
~~~

Then publish the correct answer and transition to ROUND_REVEAL.

Bots use the same score rules internally. To avoid unnecessary live task volume, a bot’s wrong-answer penalty may be projected at round resolution rather than at its planned answer instant. This does not change score, outcome, or the information available to humans.

## 3.4 Difficulty order

Normal Quick Battle uses:

- Questions 1–2: Easy.
- Questions 3–7: Medium.
- Questions 8–10: Hard.

Declared difficulty is used until empirical data is reliable. Once reliable, use language-and-mode-specific empirical difficulty while preserving the same target bands.

## 3.5 Category behaviour

At launch, public matchmaking exposes only **Mixed** category.

Mixed Quick Battle selection:

- Aim for at least six distinct main categories across ten normal questions when inventory allows.
- Maximum two questions from one main category in a normal match.
- Avoid the same subcategory in consecutive questions.
- Never weaken answer-quality, language, or exposure restrictions merely to satisfy category diversity.

Category-specific queues exist behind a server feature flag and remain disabled until the liquidity and inventory activation gates are met.

## 3.6 Option order

- Every player receives an independently shuffled order of the same four conceptual options.
- The backend stores conceptual option IDs.
- A player-private projection maps display position to conceptual option ID.
- The public projection never contains every player’s option mapping.
- Client-submitted option ID must belong to the current player-private option set.

## 3.7 Results ranking

After Question 10, rank players by:

1. Normal-match score descending.
2. Number of normal-question wins descending.
3. Mean authoritative winning response time ascending. A player with zero normal-question wins has **+infinity** for this criterion.
4. Deterministic server tie value ascending: HMAC(server_tiebreak_key, match_id + ":" + uid).

If two or more players tie for **first place on normal-match score**, do not use criteria 2–4 to select the winner. Enter Sudden Death.

## 3.8 Sudden Death

Sudden Death applies only to players tied for the highest normal score.

- Non-tied players become spectators.
- Round duration remains 11.0 seconds.
- First Sudden Death question is Medium; later ones are Hard.
- First eligible player to submit a correct answer wins the match.
- A wrong answer locks that player for the current Sudden Death question only. It does not alter normal score.
- No-answer has no score effect.
- Sudden Death answer outcomes contribute to question-quality statistics but not normal score, normal-question-win count, score XP, or rank MMR formula.
- Spectators may watch and send at most one curated reaction per Sudden Death question.
- The winner becomes place 1. Remaining originally tied players are ordered by the standard secondary rules in Section 3.7.
- A maximum of five unresolved Sudden Death questions is allowed. If no eligible player answers correctly after five, select the winner using: number of normal-question wins, then mean winning response time, then deterministic HMAC tie value. This prevents an endless match.

---

# 4. GAME MODE 2 — SURVIVAL

## 4.1 Core rules

- Ten roster slots.
- Human and bot slots are allowed.
- Each round has an 11.0-second answer window unless it is an explicitly defined rescue/tiebreak round.
- Every active player may submit one answer.
- Correctness remains hidden until round resolution.
- Incorrect answer normally eliminates the player.
- No answer normally eliminates the player.
- Continue until one winner exists.

During ROUND_ACTIVE, clients may show that another player has locked an answer, but must not reveal correctness, selected option, correct answer, elimination, or survival status.

## 4.2 Normal resolution

At round end:

- Correct active players survive.
- Wrong-answering active players are eliminated.
- Active players who submitted no answer are eliminated.
- If one active player remains, finish immediately without starting another question.
- If two or more active players remain, continue with the next round.

## 4.3 All-wrong and zero-answer protection

The game must never loop indefinitely and must never reward coordinated non-participation.

Definitions:

- **unresolved_round_streak** increments when no active player answers correctly in a round.
- It resets to zero after a round with at least one correct survivor.
- A rescue/tiebreak round uses a fresh question and cannot repeat the same question group.

Rules:

1. **At least one answer submitted; all submitted answers wrong**
   - Wrong-answering players are protected for this one round.
   - Players who submitted no answer are eliminated normally.
   - If one player remains after those eliminations, that player wins.
   - Otherwise start a fresh rescue round at one difficulty band lower, never lower than Easy.

2. **No active player submits an answer**
   - Do not silently replay indefinitely.
   - Start one fresh Easy rescue round with a 15-second answer window.
   - The rescue round is visibly labelled as a tiebreak/rescue round.

3. **Three consecutive unresolved rounds**
   - Start one final 15-second Easy SURVIVAL_TIEBREAK round.
   - No-answer in this final tiebreak eliminates the player.
   - If the final tiebreak still does not produce a unique survivor, resolve remaining placements deterministically by:
     1. Number of correct Survival rounds in the match, descending.
     2. Sum of authoritative response times for correct Survival rounds, ascending.
     3. HMAC(server_tiebreak_key, match_id + ":" + uid), ascending.
   - The first player by this order is the winner.

For the terminal deterministic ordering, use every player who was active at the start of SURVIVAL_TIEBREAK if the final tiebreak eliminates everyone. Store that starting active set in authoritative state before the tiebreak begins.

This rule prevents both an infinite all-wrong loop and an exploit in which every player simply waits out hard questions.

## 4.4 Difficulty progression

Difficulty is selected from server configuration:

~~~text
8–10 active players -> Easy / Medium, weighted toward Easy
5–7 active players  -> Medium
3–4 active players  -> Medium / Hard, weighted toward Hard
2 active players    -> Hard
~~~

Rescue and final tiebreak rules override this table as specified above.

## 4.5 Placement

- Winner = place 1.
- Players eliminated in one normal round share a placement band.
- MMR computes a tie between members of the same placement band.
- Final tiebreak deterministic ordering creates unique terminal placements only when the unresolved cap is reached.

## 4.6 Eliminated users

An eliminated human may:

- Watch Battle.
- Leave / Play Again after the match finalises.

Spectators:

- May send one curated reaction per remaining round.
- May not answer, re-enter, alter match state, or reveal information.

# 5. CURATED REACTION SYSTEM

There is no free-text match chat.

The reaction catalog contains only server-managed IDs, for example:

~~~text
emoji_laugh       -> 😂
emoji_fire        -> 🔥
emoji_clap        -> 👏
emoji_shock       -> 😱
emoji_mindblown   -> 🤯
text_gg           -> GG!
text_nice         -> Nice!
text_wow          -> Wow!
text_oops         -> Oops!
text_come_on      -> Come on!
~~~

Rules:

- One reaction per player per question/round.
- A reaction is sent as a reaction ID only; arbitrary text is never accepted.
- The backend verifies participant/spectator eligibility, state, round ID, catalog version, activation status, and per-round quota.
- Reactions appear for 1.5–2.0 seconds and must not cover question text, options, timer, or a tap target.
- The reaction catalog is localisation-ready, versioned, and admin-managed.
- A blocked user’s reaction is hidden from the blocking user and vice versa.
- Reactions are non-authoritative social events. They never affect timing, score, answer status, bot behaviour, or ranking.

---

# 6. SOCIAL SYSTEM

## 6.1 Friends

Users can:

- Search an exact or prefix username through a server-controlled search endpoint.
- Send a friend request.
- Accept or decline a request.
- Remove a friend.
- Block a player.
- Report a player.
- Challenge a friend.

Rules:

- Friend requests are directional until accepted, then a canonical friendship edge is created.
- Duplicate friend requests are idempotent.
- A block immediately prevents new friend requests, challenges, and social notifications in both directions.
- Existing friendship may remain stored for audit but is hidden and non-interactive while a block exists.
- Username search is rate-limited and returns only the minimum safe profile: UID-derived public ID, display username, avatar ID, league summary if enabled, and relationship state.
- Never reveal email, device information, location, account age beyond a public badge, or block reason.

## 6.2 Friend Challenge

Friend Challenge reuses the standard Quick Battle engine. There is no separate 1v1 ruleset.

Party rules:

- The host creates a temporary party with a cryptographically random party ID and invite tokens.
- Party mode is Quick Battle.
- Party contains 2–4 accepted human participants.
- Host chooses the question language; invitees must explicitly accept that language before joining.
- The host may invite up to three friends.
- Party invitation expires after 60 seconds.
- The host may start when at least two humans have accepted, or the party auto-starts at expiry if at least two humans have accepted.
- Missing roster slots are filled with bots.
- A user can belong to only one waiting party, queue ticket, or active match at a time.
- A party member may leave before start. If fewer than two humans remain, the party cancels with no progression change.
- Deep links contain only an opaque invite token; the backend validates invitation, expiry, party capacity, block state, and authenticated user before joining.

## 6.3 Rematch

- After a settled match, show Rematch for 10 seconds.
- Only humans from the prior match may accept.
- Accepted humans form a new temporary roster; missing slots are filled by bots.
- Question selection for rematch happens only after the prior match settlement has committed exposure history. A rematch must not repeat a question group shown in the prior match merely because persistence was delayed.
- A rematch has a new match ID, new bot plans, new question manifest selection, and a new MMR snapshot.
- No human is forced to wait beyond the 10-second window.

---

# 7. PROGRESSION, MMR, AND ECONOMY

## 7.1 XP and levels

XP is permanent. It never decreases.

Quick Battle base match XP:

~~~text
participation_xp = 10
score_xp = max(final_normal_match_score, 0)
placement_bonus:
  1st = 40
  2nd = 25
  3rd = 15
  4th = 10

base_match_xp = participation_xp + score_xp + placement_bonus
~~~

Survival base match XP:

~~~text
participation_xp = 10
survival_round_xp = 8 * completed_survival_rounds
placement_bonus:
  1st  = 60
  2nd  = 40
  3rd  = 30
  4th  = 20
  5th  = 15
  6th  = 10
  7th  = 8
  8th  = 6
  9th  = 4
  10th = 2

base_match_xp = participation_xp + survival_round_xp + placement_bonus
~~~

For Survival, **completed_survival_rounds** counts only rounds that reached a normal or explicit tiebreak resolution with at least one accepted answer. A zero-answer rescue round does not generate extra round XP.

Level curve:

~~~text
xp_to_start_level(1) = 0
xp_to_start_level(L) = round(100 * (L - 1)^1.6), for L >= 2
~~~

The backend computes the level from total XP. The client may display a local preview only.

## 7.2 Rewarded XP

Rewarded advertising is optional and is never a competitive advantage.

- A successfully server-verified reward grants **one additional copy of that match’s base match XP**.
- Thus total lifetime XP for a rewarded match is 2x base match XP.
- Reward bonus XP affects lifetime XP and cosmetic/level progression only.
- Reward bonus XP does **not** affect ranked weekly XP, MMR, league, placement, streak, crown, question score, mission count, or badge counters that mean completed matches.
- Default cap: five successful rewarded XP grants per UID per UTC day.
- The cap and offer visibility are server configuration, not client authority.
- A failed, missing, late, duplicate, or invalid verification never grants the bonus.

## 7.3 Matchmaking rating and leagues

Maintain server-only numeric MMR.

New players:

- Start at MMR 1000.
- First five **ranked-eligible** completed matches are placement matches.
- During placement, league display is Unranked.
- Provisional K multiplier applies for the first 20 ranked-eligible matches.

League thresholds:

~~~text
Bronze   < 900
Silver   900–1049
Gold     1050–1199
Platinum 1200–1349
Diamond  1350–1499
Master   1500–1699
Legend   >= 1700
~~~

The match record stores immutable **pre_match_mmr** for every participant. Rating is calculated from those snapshots, never from a profile that may have changed while the match was running.

Pairwise Elo for player i against opponent j:

~~~text
expected = 1 / (1 + 10 ^ ((rating_j - rating_i) / 400))
actual = 1.0 if i places above j
       = 0.5 if tied
       = 0.0 if below j
~~~

Quick Battle:

~~~text
K = 32
rating_delta = round(K * average(actual - expected across opponents))
~~~

Survival:

~~~text
K = 40
rating_delta = round(K * average(actual - expected across opponents))
~~~

For the first 20 ranked-eligible matches:

~~~text
effective_K = base_K * 1.5
~~~

Bots have fixed configured MMR values. Bot MMR never changes. Bots can be included in expected-outcome calculations only in a ranked-eligible match.

## 7.4 Bot-match economy policy

Bot availability is necessary for low queue times, but bot farming must not distort competitive systems.

- All completed, non-cancelled matches may award base XP, mission progress, and category performance stats.
- A match is **ranked-eligible** only if it meets the human-opponent rule below.
- Only ranked-eligible matches may change MMR, placement-match count, league, ranked weekly XP, or Quick Battle win streak.
- Survival crowns are awarded only for ranked-eligible Survival victories.
- Match history always stores human slot count, bot slot count, and ranked-eligibility reason.

## 7.5 Minimum human-opponent rule

Default ranked eligibility:

| Mode | Minimum other human opponents | Minimum total humans |
|---|---:|---:|
| Quick Battle | 2 | 3 |
| Survival | 3 | 4 |

Server configuration may make the requirement stricter, never weaker without a documented product decision.

## 7.6 Weekly leaderboard

The leaderboard uses **ranked_weekly_xp**, not all lifetime XP and not reward bonus XP.

- Week identifier: UTC ISO week.
- One Firestore document per UID/week.
- No global reset job is required.
- Sort order: ranked_weekly_xp descending, quick_wins descending, survival_crowns descending, deterministic UID hash ascending.
- Global leaderboard exists at launch.
- League-filtered leaderboard is optional.
- Country-filtered leaderboard is deferred; never infer or expose precise location.

## 7.7 Win streak and crowns

Maintain:

- quick_current_ranked_win_streak
- quick_best_ranked_win_streak
- survival_ranked_crowns_lifetime

Rules:

- A ranked-eligible first-place Quick Battle increases current streak.
- A ranked-eligible Quick Battle loss or voluntary abandonment resets current streak.
- Non-ranked bot-heavy matches do not increase or reset the ranked streak.
- Survival uses crowns rather than a cross-mode streak.

## 7.8 Daily and weekly missions

Daily missions:

- Three per UTC day.
- Generated deterministically or lazily per UID/date.

Weekly missions:

- Three to five per UTC ISO week.

Possible templates:

- Play three Quick Battles.
- Win one ranked-eligible Quick Battle.
- Win five Quick Battle questions.
- Earn 100 Quick Battle normal-score points cumulatively.
- Play one Survival match.
- Reach ranked-eligible Survival top 3.
- Answer ten questions correctly.
- Send five reactions across different rounds.

Mission principles:

- A rewarded XP multiplier never doubles mission progress.
- A cancelled match gives no mission progress except a server-configured technical-compensation rule.
- Mission completion and claim are server-authoritative and idempotent.

## 7.9 Badges and frames

Examples:

- First Quick Win.
- 10 ranked Quick Wins.
- Five ranked-win streak.
- First ranked Survival Crown.
- 10 ranked Survival Crowns.
- Geography Specialist.
- Science Specialist.
- Diamond League frame.
- Legend League frame.

No badge, frame, avatar, or cosmetic changes gameplay.

---

# 8. GLOBAL QUESTION CATEGORIES

There are exactly nine main categories:

1. Geography & World
2. Science & Nature
3. History
4. Sports
5. Movies & TV
6. Music
7. Food & Culture
8. Technology & Inventions
9. Arts & Literature

There is no Gaming main category. Mixed is a matchmaking selection, not a database category.

## 8.1 Global relevance

Competitive questions must be globally reasonable.

~~~text
global_relevance_score = 1..5
competitive pool requirement = global_relevance_score >= 4
~~~

Accepted examples:

- FIFA World Cup, Olympic Games, NBA Finals, Formula 1, Grand Slam tennis, globally recognised athletes.
- Hollywood, Bollywood, globally distributed franchises, international streaming hits, Oscars.
- Internationally recognised artists, bands, instruments, albums, awards, and music history.

Rejected examples:

- Local reserve-team players or regional league trivia.
- Domestic celebrities or programmes known mainly in one market.
- Short-lived local rankings or statistics.

## 8.2 Suggested subcategories

| Main category | Suggested subcategories |
|---|---|
| Geography & World | Countries, capitals, flags, maps, cities, landmarks, rivers, mountains, islands, oceans, UNESCO / World Heritage |
| Science & Nature | Animals, plants, space, human body, biology, physics, chemistry, earth science, environment |
| History | Ancient civilisations, world wars, exploration, empires, historical figures, historical inventions, archaeology |
| Sports | World Cup, Olympics, global football, basketball, tennis, Formula 1, athletics, major international competitions |
| Movies & TV | Hollywood, Bollywood, global films, global TV/streaming, Oscars and major awards, directors, famous characters/franchises |
| Music | Global artists, bands, instruments, albums, music history, major international awards |
| Food & Culture | World cuisines, famous dishes, ingredients, global traditions, festivals, cultural symbols |
| Technology & Inventions | Computers, internet, AI basics, smartphones, famous inventions, inventors, space technology, global technology history |
| Arts & Literature | Famous painters, famous works, public-domain art, world literature, authors, architecture, mythology, art movements |

---

# 9. QUESTION QUALITY STANDARD

Every competitive question must satisfy all conditions:

- Exactly one unambiguously correct option.
- Exactly four answer options.
- No all-of-the-above or none-of-the-above.
- No trick wording based mainly on grammar.
- No double negatives.
- No local-only knowledge.
- No rapidly changing fact unless review lifecycle is configured.
- Source/reference evidence exists internally.
- Question version is verified.
- Match-language translation is verified.
- Content is suitable for 13+ positioning.

Translation constraints:

~~~text
question preferred length <= 120 characters
question hard maximum    <= 160 characters
answer preferred length  <= 32 characters
answer hard maximum      <= 48 characters
~~~

Questions exceeding hard limits are not competitive eligible.

## 9.1 Media

All question and article images delivered by the content pipeline use WebP.

Competitive media rules:

- WebP, mobile-optimised.
- Preferred size <= 150–200 KB.
- Maximum useful display dimension approximately 1024 px unless justified.
- Store aspect ratio and accessibility alt-text metadata.
- Avoid layout shift.
- Store source, author, license, attribution, copyright status, and review status.
- Do not scrape/distribute copyrighted movie stills, album covers, celebrity photos, or sports photography without suitable rights.
- Prefer public-domain, compatible licensed, original, or legally suitable generated assets.

A media-dependent question cannot start if the server detects its delivery asset is missing or invalid. Replace it with a reserve question before public round start.

## 9.2 Time-sensitive questions

Fields:

~~~text
time_sensitive: boolean
review_after: timestamp | null
~~~

If review_after expires, the question leaves competitive selection automatically until revalidated. Prefer durable historical facts over current-president, current-ranking, or current-number-one questions.

## 9.3 Status workflow

~~~text
DRAFT
-> GENERATED
-> VALIDATION_PENDING
-> VERIFIED
-> ACTIVE
-> QUARANTINED
-> RETIRED
~~~

Competitive selection requires:

~~~text
status = ACTIVE
verified = true
competitive_enabled = true
global_relevance_score >= 4
review_after is null or in the future
translation_verified = true
competitive_text_valid = true
~~~

---

# 10. SHARED QUESTION PLATFORM

Questions are never copied into separate Synova and Live Trivia datasets.

Shared:

- Question groups and versions.
- Translations and answer concepts.
- Categories and subcategories.
- Licensed media and metadata.
- Quality workflow, source evidence, and reports.
- Difficulty statistics.
- Global user exposure history.

Product-specific:

- Live Trivia progression, league, friends, missions, ads, purchases, game achievements, and match history.
- Synova solo progression and product-specific sessions.

## 10.1 Question group, translation, and answer key

One fact is represented by one **question group**. Translations are children of the conceptual question.

Example:

~~~text
question_group_id: random stable ID
qid: sequential integer for compact exposure history
category: geography
image: flag_x.webp
correct answer: server-only concept ID "italy"

en: Which country does this flag belong to?
tr: Bu bayrak hangi ülkeye aittir?
es: ¿A qué país pertenece esta bandera?
~~~

The correct concept ID belongs only in a server-readable private-answer record or copied server-only match state. It must never be stored in a document that a mobile client can read.

## 10.2 Global exposure history

For every authenticated user, maintain a compact ordered list of the most recent **2,500 unique qids** shown across Synova and Live Trivia.

At match selection:

1. Load recent qid lists of all human participants.
2. Union them.
3. Exclude the union where viable.
4. Ignore bot exposure for filtering.
5. Never repeat a question group inside one match.

Fallback order:

1. Exclude last 2,500.
2. If insufficient, exclude last 1,000.
3. If insufficient, exclude last 300.
4. If still insufficient, prefer least-recently-seen candidates.

Exposure write rules:

- Record only question groups actually published to a player, not every preselected reserve.
- Buffer shown qids in canonical match state.
- At settlement or cancellation recovery, append shown qids once per human in one idempotent transaction.
- A user cannot enter a second Live Trivia match or party while that user’s prior Live Trivia settlement is pending.
- Synova uses the same server-owned exposure service. A Synova solo session may continue independently, but every shared exposure append retries transactionally against the same user_recent_questions record.

## 10.3 Difficulty statistics

Maintain empirical difficulty by:

~~~text
question_group
question_version
language
mode
~~~

Track:

- impressions
- human attempts
- correct
- wrong
- no answer
- censored_by_early_quick_winner
- response-time aggregates
- report counts

Bots never affect human difficulty learning.

Quick Battle is censored after the first correct answer. Players denied an opportunity to answer are counted as censored, not as ordinary no-answer observations. Survival and Synova data carry greater weight than raw Quick Battle accuracy for difficulty calibration.

Do not replace declared difficulty before at least 200 valid human attempts for that language/mode/version.

---

# 11. QUESTION CONTENT PIPELINE AND ADMIN

Build an internal admin application.

Recommended stack:

- Next.js.
- Firebase Auth.
- Admin custom claim.
- MFA required for admin accounts.
- Backend admin APIs only; no privileged service account credentials in browser code.

Required admin areas:

1. Questions list, search, and filters.
2. Question create, edit, version, retire, and restore.
3. Translation management.
4. Category/subcategory management.
5. Media upload and license metadata.
6. AI batch generation jobs.
7. Validation queue.
8. Duplicate detection.
9. Question reports and quarantine.
10. Player reports and moderation.
11. Bot profile catalog.
12. Avatar and reaction catalog.
13. Versioned server configuration.
14. Pool-health dashboard.
15. User sanctions and audit log.

## 11.1 AI generation

AI-generated content begins in DRAFT or GENERATED. It never enters the competitive pool automatically.

Inputs:

- Main category.
- Subcategory.
- Declared difficulty.
- Canonical language.
- Required translations.
- Number of candidates.
- Global relevance requirement.
- Media requirement.

Pipeline:

~~~text
Versioned prompt
-> Candidate generation
-> Normalisation
-> Exact duplicate check
-> Semantic duplicate check
-> Answer validation
-> Global relevance validation
-> Translation generation
-> Length validation
-> Source/provenance collection
-> Human review
-> VERIFIED
-> ACTIVE
~~~

Store provider/model/prompt version metadata for audit. A cited source generated by AI is not trusted until human review validates it.

## 11.2 Duplicate detection

Use:

- Normalised exact-text hash.
- Concept/fact hash where possible.
- Semantic embedding similarity for paraphrased near duplicates.

Near-duplicate threshold is versioned server config. A paraphrase of the same fact is normally rejected rather than counted as a distinct question group.

## 11.3 Question reports

Players can report:

- Wrong answer.
- Ambiguous question.
- Outdated information.
- Image problem.
- Translation problem.
- Other predefined reason.

Rules:

- One report per user/question-version/reason within a configured period.
- Reports are server-authenticated and rate-limited.
- Automatic quarantine default: at least 10 unique reporters and report rate >= 2%, or an admin action.
- Quarantine immediately removes the affected version from future manifests.
- Existing live matches may finish only if the question is already active; never replace a current question mid-round. Record the issue for review.

# 12. CONTENT AND QUEUE ACTIVATION GATES

## 12.1 Pool manifests

Do not query tens of thousands of Firestore documents for every match.

Build versioned compressed manifests by:

~~~text
language
main category
subcategory
difficulty
mode eligibility
question version
~~~

Example:

~~~text
/question-pools/en/mixed/easy/v42.json.gz
/question-pools/en/mixed/medium/v42.json.gz
/question-pools/en/mixed/hard/v42.json.gz
~~~

Manifest contains only lightweight server-selection metadata and qids. It never contains answer keys, source references, or client-delivery URLs.

Cloud Run instances cache manifests in memory with version checking. The manifest version record is server-readable only. Quarantined content invalidates the relevant manifest version before any new match can select it.

## 12.2 Language activation gate

A competitive language cannot be enabled merely because UI translation exists.

Soft-launch language minimum:

~~~text
at least 6,000 active verified question groups
at least 1,500 active groups in each difficulty band
all nine main categories represented
selection simulation success >= 99.0%
~~~

Full 10,000-human production language minimum:

~~~text
at least 12,000 active verified question groups
at least 2,500 Easy, 4,000 Medium, 2,500 Hard
all nine main categories represented in every difficulty where editorially valid
selection simulation success >= 99.5% for four-player recent-history unions
report rate below configured safety threshold
~~~

Selection simulation means at least 1,000 synthetic roster trials using realistic recent-history unions. Each trial must successfully choose normal and reserve questions while obeying language, status, diversity, and exposure constraints.

## 12.3 Category queue activation gate

Public category-specific queues remain disabled until all conditions hold for the relevant language/category:

- Human-only Quick Battle rate is consistently high.
- p95 matchmaking wait remains within target.
- Sufficient DAU exists in that language.
- The category inventory satisfies the language activation distribution for its demand.
- Analytics shows sustained category demand.

Use a server feature flag by language and region. Do not enable category queues just because total registrations are high.

# 13. HIGH-LEVEL TECHNICAL ARCHITECTURE

Use Firebase and Google Cloud initially. Do not use AWS for this product in v1.

~~~text
                     FLUTTER CLIENTS
               Synova          Live Trivia
                    \            /
                     \          /
               Firebase Auth + App Check
                         |
              HTTPS Load Balancer + Cloud Armor
                         |
                    CLOUD RUN
                  FastAPI Backend
                         |
      +------------------+---------------------+
      |                  |                     |
  FIRESTORE          RTDB SHARD RING       CLOUD STORAGE
 persistent data     live match state       versioned WebP
 questions/users     public/private state    signed delivery
 queues/history      reactions/presence
      |
 CLOUD TASKS + CLOUD SCHEDULER
 resolver recovery, settlement, cleanup, maintenance
~~~

Additional Firebase/GCP services:

- Firebase Analytics.
- Crashlytics.
- Remote Config.
- FCM.
- Secret Manager.
- Cloud Logging and Monitoring.
- Cloud Build.
- AdMob.
- Google Play Billing.
- Apple StoreKit / App Store Server API.

## 13.1 Main implementation stack

Mobile:

- Flutter.
- Riverpod.
- go_router.
- Firebase Flutter SDKs.
- Drift only for non-authoritative local cache and preferences.

Backend:

- Python.
- FastAPI.
- Pydantic v2.
- Firebase Admin SDK / Google Cloud SDKs.
- Cloud Run.

Admin:

- Next.js.
- Firebase Auth.
- Backend admin APIs.

## 13.2 Region and latency policy

The initial production primary region is **europe-west1**.

- Firestore, Cloud Run, Cloud Tasks, Cloud Storage, and every live RTDB shard must use compatible European locations with the lowest supported cross-service latency.
- Before creating production projects, validate current service availability in the selected location. If a named service is unavailable, select one alternative supported European region once and record it in infrastructure source control. Do not split services across continents.
- Soft launch is region-scoped. Global multi-region matchmaking is not a v1 claim.
- A player is matched only within the same configured serving region and latency compatibility policy.
- Multi-region expansion requires a separate architecture decision, new regional queue partitions, regional live-shard rings, and no cross-region first-answer competition.

## 13.3 Cloud Run execution model

Cloud Run is stateless between requests.

- FastAPI handlers must be async-safe.
- Any blocking Firebase/Admin SDK operation must execute through a bounded worker/thread strategy; do not block the event loop.
- Concurrency is tuned by load test, not assumed. Initial stage values are 2 vCPU, 2 GiB memory, concurrency 20, min instances 2, max instances 50.
- Production 10k configuration is set only after the 10k load tests pass. Configure quota, min/max instances, concurrency, CPU, and thread count together.
- No game correctness may depend on a Cloud Run instance retaining memory, a local timer, a local queue, or sticky requests.

---

# 14. ENVIRONMENTS AND INFRASTRUCTURE

Use separate Firebase/GCP projects:

~~~text
quiz-platform-dev
quiz-platform-stage
quiz-platform-prod
~~~

Never share production databases, service accounts, secrets, ad IDs, or IAP credentials with dev/stage.

Each environment has:

- Separate Firebase configuration.
- Separate Firestore database.
- Separate Cloud Storage buckets.
- Separate RTDB live-shard ring.
- Separate Firebase App Check configuration.
- Separate service accounts and secrets.
- Test AdMob/IAP configuration outside production.
- Independently deployed RTDB rules for every shard.

## 14.1 RTDB shard ring

Live match traffic uses a fixed ring of **16 RTDB shards** in production:

~~~text
live-00
live-01
...
live-15
~~~

Stage uses at least four shards; dev uses at least two. This prevents the codebase from assuming a single RTDB URL.

Shard assignment:

~~~text
shard_index = first_uint32(HMAC(match_shard_key, match_id)) mod 16
~~~

Rules:

- A match is assigned exactly one shard at creation and never moves while active.
- Firestore match_index stores the shard ID and client-safe RTDB URL selector.
- A client connects only to its current match shard, not all shards.
- A user leaving a match detaches all listeners from that shard.
- Shard count can expand only through a versioned ring migration plan. Existing active matches remain on their assigned shard.
- Every shard has identical schema and security rules.

## 14.2 Infrastructure as code

Version-control all non-secret infrastructure/configuration:

~~~text
firebase.json
firestore.rules
firestore.indexes.json
rtdb/live-shard.rules.json
cloudbuild.yaml
cloudrun.yaml
cloudarmor.yaml
cloudtasks.yaml
storage.rules
Dockerfile
scripts/
~~~

Secrets never enter source control.

---

# 15. AUTHENTICATION, APP CHECK, AND SESSION BOOTSTRAP

Supported sign-in:

- Google.
- Apple.
- Email/password or email-link.

If third-party sign-in is offered on iOS, include Sign in with Apple.

Live multiplayer requires an authenticated account.

First-run flow:

~~~text
Launch
-> 13+ declaration
-> Terms / Privacy acceptance
-> Sign in / Create account
-> Unique username
-> Curated avatar
-> Tutorial
-> Home
~~~

## 15.1 Session bootstrap

POST /v1/session/bootstrap returns only safe session data:

- Profile summary.
- Product/account status.
- Server time and a non-authoritative estimated client clock offset.
- Enabled features.
- Active queue/party/match pointer if one exists.
- Current server configuration display version.
- Current catalog versions.
- Current question-language availability.

It must not return answer keys, raw server configuration, bot plans, secrets, internal risk score, or private moderation notes.

## 15.2 App Check

Enable Firebase App Check:

- Android: Play Integrity.
- iOS: App Attest with DeviceCheck fallback where appropriate.
- Development: debug provider only in dev/stage.

Every protected mobile backend route validates:

1. Firebase ID token.
2. Firebase App Check token.
3. Account state.
4. Endpoint-specific rate and state limits.

App Check reduces abuse but is not the sole anti-cheat control.

---

# 16. FIRESTORE RESPONSIBILITIES

Firestore stores persistent, non-hot data. It is not the live answer bus.

## 16.1 Canonical collections

~~~text
users/{uid}
public_profiles/{uid}
user_runtime/{uid}
username_registry/{username_normalized}
friend_requests/{request_id}
friendships/{ordered_uid_pair}
blocks/{blocker_uid}_{blocked_uid}
player_reports/{report_id}
moderation_actions/{action_id}

question_groups/{question_group_id}
question_translations/{question_group_id}_{language}_{version}
question_private/{question_group_id}_{version}
question_stats_shards/{question_version_language_mode}/shards/{shard_id}
question_stats_summaries/{question_version_language_mode}
question_reports/{question_group_id}_{version}_{uid}_{reason}
media_assets/{media_asset_id}
categories/{category_id}
subcategories/{subcategory_id}
pool_manifest_versions/{language}_{mode}_{difficulty}

matchmaking_tickets/{ticket_id}
parties/{party_id}
match_index/{match_id}
match_history/{match_id}
match_settlements/{match_id}
user_recent_questions/{uid}
user_progression_events/{uid}_{sequence}
weekly_user_stats/{week_id}_{uid}
user_missions/{uid}_{period_id}

avatar_catalog/{avatar_id}
reaction_catalog/{reaction_id}
bot_profiles/{bot_id}
server_config/{config_name}
purchase_entitlements/{uid}
purchase_transactions/{store}_{transaction_id}
reward_offers/{offer_id}
reward_grants/{offer_id}
deletion_requests/{uid}
audit_log/{audit_id}
~~~

## 16.2 Mutation ownership

| Data | Client direct write | Backend write | Notes |
|---|---|---|---|
| User profile identity | No | Yes | Username/avatar changes use validated APIs. |
| User local preference | Narrowly allowed if explicitly safe | Yes | Never authoritative. |
| Queue ticket | No | Yes | Firestore transaction / backend only. |
| Match state | No | Yes | RTDB shard only. |
| XP/MMR/league/missions | No | Yes | Settlement ledger only. |
| Purchases/rewards | No | Yes | Verified store/ad callbacks only. |
| Question content | No | Admin backend only | Client cannot read raw answer records. |
| Friendship/block/report | No | Yes | Client invokes validated API. |
| Presence | Optional limited path only | Yes | No score or game authority. |

## 16.3 Direct client policy

Default Firestore rule is deny. Permit direct client read/write only when a specific safe path and security rule are documented. The mobile apps must not directly update:

- XP, MMR, league, weekly XP, streak, crowns, or achievements.
- Username ownership.
- Match results or question statistics.
- Purchases or ad entitlements.
- Friendship acceptance state.
- Moderation/sanction status.
- Recent-question history.
- Server configuration.

## 16.4 Required indexes and TTL

Create and test these Firestore indexes before stage launch:

| Collection | Query purpose | Required ordered fields |
|---|---|---|
| matchmaking_tickets | Compatible human candidate scan | state, mode, language, region, latency_band, created_at |
| matchmaking_tickets | MMR-band candidate scan | state, mode, language, region, latency_band, mmr_snapshot, created_at |
| weekly_user_stats | Global weekly leaderboard | week_id, ranked_weekly_xp descending, quick_ranked_wins descending, survival_ranked_crowns descending, tie_break_hash |
| friend_requests | Recipient inbox | recipient_uid, state, created_at descending |
| question_reports | Admin review | status, created_at descending |
| moderation_actions | User sanction history | target_uid, created_at descending |
| match_history | User history | participant_uid array-contains, completed_at descending |

TTL/cleanup fields:

~~~text
idempotency record expiry: 48 hours
matchmaking ticket expiry: created_at + 60 seconds, retain audit-safe terminal state for 24 hours
reward offer expiry: 15 minutes
live match index expiry: after live-state cleanup
short-lived presence expiry: 90 seconds without heartbeat
~~~

TTL cleanup does not define authoritative timing. The backend checks expiry in every relevant action.

---

# 17. RTDB LIVE MATCH DATA CONTRACT

Each live match exists entirely in one root on its assigned RTDB shard:

~~~text
/matches/{match_id}/
  public/
  player_private/{uid}/
  authoritative/
  presence/
~~~

The backend performs a transaction at **/matches/{match_id}**, not separately on public and private branches. This makes public projection, player-private projection, and authoritative state change atomically together.

## 17.1 Public projection

Client-readable to an authorised active participant or spectator:

~~~text
public/
  schema_version
  match_id
  mode
  match_phase
  language
  region
  state
  state_version
  config_version
  round_id
  round_number
  starts_at_ms
  ends_at_ms
  reveal_ends_at_ms
  next_server_event_at_ms
  designated_resolver_uid
  current_question:
    qid
    question_group_id
    question_version
    text
    signed_image_url
    image_expires_at_ms
  participants:
    {participant_id}:
      display_name
      avatar_id
      is_bot
      active
      answer_locked
      score
      survival_status
  correct_answer_reveal: null | safe display payload
  events: bounded event list
  result_summary: null | safe final result
~~~

Before ROUND_REVEAL, correct_answer_reveal is null. Public data never contains future question payloads, player-specific option mappings, selections, answer concepts, bot plans, private risk data, or source references.

## 17.2 Player-private projection

Readable only by the matching authenticated UID:

~~~text
player_private/{uid}/
  schema_version
  round_id
  option_order:
    display_position -> concept_id
  own_answer_status:
    NOT_ANSWERED | ANSWERED_WRONG | ANSWERED_CORRECT | LOCKED | INELIGIBLE
  eligible_to_answer
  reaction_used
  signed_media_fallback_url_if_needed
~~~

A spectator has no option order or answer status.

## 17.3 Authoritative projection

Server-only:

~~~text
authoritative/
  schema_version
  match_id
  shard_id
  match_phase
  state
  state_version
  round:
    round_id
    question_group_id
    question_version
    correct_concept_id
    starts_at_ms
    ends_at_ms
    reveal_ends_at_ms
    question_kind
  selected_question_plan
  reserve_question_plan
  participants:
    uid_or_bot_id:
      type
      pre_match_mmr
      score
      active
      answer_record
      response_metrics
      reaction_record
  bot_plans
  shown_qids_by_human
  unresolved_round_streak
  scheduled_event_ids
  settlement:
    status
    idempotency_key
    progression_sequence_by_uid
  audit:
    state_transition_log
    config_snapshot
~~~

The authoritative branch is never client-readable.

## 17.4 RTDB security rules

Rules must enforce:

- Default deny.
- A participant may read public data only while listed as an authorised participant.
- An authorised spectator may read only public data.
- A participant may read only player_private/{auth.uid}.
- No client can read authoritative.
- No client can write public, player_private, authoritative, or score/state fields.
- Presence writes, if enabled, are limited to the authenticated user’s own small safe payload and cannot carry game state.
- Security-rule tests must prove every path above.

## 17.5 Events and retention

- Events use monotonically increasing event_sequence.
- Public event list is bounded to the latest 40 events.
- Clients reconnect by state version; they do not rely solely on a complete event history.
- Live match roots are marked for cleanup only after settlement has succeeded.
- Cleanup removes live state after the configured retention window, default 30 minutes after settlement.

---

# 18. CORE DATA MODELS

All examples are semantic contracts. Exact SDK field casing may be snake_case, but names and meaning must remain stable.

## 18.1 User

~~~json
{
  "schema_version": 1,
  "uid": "firebase_uid",
  "username_display": "Hakan",
  "username_normalized": "hakan",
  "avatar_id": "av_012",
  "created_at": "timestamp",
  "age_gate_passed": true,
  "age_gate_verified_at": "timestamp",
  "terms_version": "2026-01",
  "terms_accepted_at": "timestamp",
  "privacy_version": "2026-01",
  "privacy_accepted_at": "timestamp",
  "question_language": "en",
  "ui_language": "tr",
  "total_xp": 12450,
  "mmr": 1125,
  "league": "GOLD",
  "placement_matches_completed": 5,
  "ranked_matches_completed": 18,
  "quick_current_ranked_win_streak": 4,
  "quick_best_ranked_win_streak": 11,
  "survival_ranked_crowns_lifetime": 7,
  "status": "ACTIVE"
}
~~~

## 18.2 User runtime lock

~~~json
{
  "schema_version": 1,
  "uid": "firebase_uid",
  "state": "IDLE",
  "active_ticket_id": null,
  "active_party_id": null,
  "active_match_id": null,
  "pending_settlement_match_id": null,
  "updated_at": "timestamp",
  "lock_version": 19
}
~~~

Allowed states:

~~~text
IDLE
QUEUED
IN_PARTY
MATCH_ACTIVE
SETTLEMENT_PENDING
DELETION_PENDING
SUSPENDED
~~~

The backend changes this document in a transaction whenever a player queues, joins a party, starts/finishes a match, or begins deletion. It prevents concurrent matches and out-of-order progression.

This runtime lock is for Live Trivia competitive activity. It does not make Synova solo content unavailable; the shared exposure service independently serialises/retries recent-question updates.

## 18.3 Question group

~~~json
{
  "schema_version": 1,
  "id": "random_doc_id",
  "qid": 18482,
  "category_id": "geography",
  "subcategory_id": "flags",
  "declared_difficulty": "EASY",
  "global_relevance_score": 5,
  "media_asset_id": "media_239",
  "time_sensitive": false,
  "review_after": null,
  "status": "ACTIVE",
  "verified": true,
  "competitive_enabled": true,
  "synova_enabled": true,
  "version": 3,
  "created_at": "timestamp",
  "updated_at": "timestamp"
}
~~~

## 18.4 Translation

~~~json
{
  "schema_version": 1,
  "question_group_id": "group_18482",
  "question_version": 3,
  "language": "en",
  "question_text": "Which country does this flag belong to?",
  "options": [
    {"concept_id": "italy", "text": "Italy"},
    {"concept_id": "spain", "text": "Spain"},
    {"concept_id": "france", "text": "France"},
    {"concept_id": "portugal", "text": "Portugal"}
  ],
  "translation_verified": true,
  "competitive_text_valid": true
}
~~~

## 18.5 Private answer

~~~json
{
  "schema_version": 1,
  "question_group_id": "group_18482",
  "question_version": 3,
  "correct_concept_id": "italy",
  "source_refs": ["source_1"],
  "verified_by": "admin_uid",
  "verified_at": "timestamp"
}
~~~

## 18.6 Match index

~~~json
{
  "schema_version": 1,
  "match_id": "match_uuid",
  "mode": "QUICK",
  "region": "europe-west1",
  "rtdb_shard_id": "live-07",
  "client_rtdb_url_selector": "live-07",
  "state": "ROUND_ACTIVE",
  "participant_uids": ["uid_a", "uid_b"],
  "created_at": "timestamp",
  "expires_at": "timestamp"
}
~~~

## 18.7 Matchmaking ticket

~~~json
{
  "schema_version": 1,
  "ticket_id": "uuid",
  "uid": "firebase_uid",
  "mode": "QUICK",
  "language": "en",
  "region": "europe-west1",
  "latency_band": "61_120",
  "mmr_snapshot": 1125,
  "created_at": "timestamp",
  "human_fill_at_ms": 0,
  "expires_at": "timestamp",
  "state": "QUEUED",
  "claim_id": null,
  "match_id": null,
  "request_id": "uuid"
}
~~~

Ticket states:

~~~text
QUEUED
CLAIMED
MATCHED
CANCELLED
EXPIRED
~~~

## 18.8 Settlement ledger

~~~json
{
  "schema_version": 1,
  "match_id": "match_uuid",
  "status": "PENDING",
  "idempotency_key": "settlement:match_uuid",
  "participant_results": {},
  "created_at": "timestamp",
  "completed_at": null,
  "retry_count": 0
}
~~~

Settlement states:

~~~text
PENDING
APPLYING
SETTLED
FAILED_RETRYABLE
CANCELLED_NO_PROGRESSION
~~~

## 18.9 Party

~~~json
{
  "schema_version": 1,
  "party_id": "uuid",
  "host_uid": "uid_a",
  "mode": "QUICK",
  "question_language": "en",
  "state": "WAITING",
  "invited_uids": ["uid_b", "uid_c"],
  "accepted_uids": ["uid_a", "uid_b"],
  "created_at": "timestamp",
  "expires_at": "timestamp",
  "match_id": null
}
~~~

Party states:

~~~text
WAITING
READY
STARTING
MATCHED
CANCELLED
EXPIRED
~~~

## 18.10 Compact match history

~~~json
{
  "schema_version": 1,
  "match_id": "uuid",
  "mode": "QUICK",
  "region": "europe-west1",
  "language": "en",
  "config_version": 7,
  "ranked_eligible": true,
  "human_slot_count": 3,
  "bot_slot_count": 1,
  "participants": [
    {
      "uid_or_bot_id": "uid_a",
      "is_bot": false,
      "place": 1,
      "normal_score": 42,
      "xp_awarded": 92,
      "mmr_delta": 18
    }
  ],
  "question_versions": [
    {"question_group_id": "group_1", "version": 3, "language": "en"}
  ],
  "completed_at": "timestamp"
}
~~~

## 18.11 Purchase entitlement

~~~json
{
  "schema_version": 1,
  "uid": "firebase_uid",
  "remove_ads": true,
  "source_store": "GOOGLE_PLAY",
  "latest_verified_transaction_id": "opaque_transaction_id",
  "state": "ACTIVE",
  "updated_at": "timestamp"
}
~~~

# 19. CLOUD RUN BACKEND RESPONSIBILITIES

One backend codebase is deployed to Cloud Run. Logical modules:

~~~text
app/
  main.py
  auth/
  profiles/
  usernames/
  accounts/
  questions/
  manifests/
  matchmaking/
  parties/
  matches/
  quick_battle/
  survival/
  bots/
  reactions/
  friends/
  missions/
  ranking/
  purchases/
  ads/
  moderation/
  analytics/
  admin/
  tasks/
  common/
~~~

Backend responsibilities:

- Verify Auth and App Check.
- Enforce account/runtime state.
- Own all matchmaking, match creation, question selection, scoring, bot planning, round resolution, settlement, progression, moderation, purchase, and reward decisions.
- Perform canonical RTDB root transactions.
- Issue short-lived signed media URLs only for active current-round delivery.
- Create Cloud Tasks only after the authoritative state transition that requires them has committed.
- Never call external network services from inside an RTDB transaction callback.

## 19.1 Idempotency contract

Every state-changing mobile request includes:

~~~text
request_id: UUIDv4
X-Idempotency-Key: UUIDv4
~~~

The backend validates that both values agree or maps the header to the body field by endpoint policy.

Rules:

- Same UID + same endpoint + same idempotency key + same semantic payload returns the original response.
- Same key with a different semantic payload returns HTTP 409 IDEMPOTENCY_KEY_REUSED.
- Answer idempotency is also stored inside the canonical match root because it affects a live transaction.
- General mutation idempotency records retain for 48 hours, then expire by TTL/cleanup.
- Settlement, store callback, and task idempotency have longer retention as required by audit/reconciliation policy.

## 19.2 Error contract

All API errors use:

~~~json
{
  "error": {
    "code": "ROUND_NOT_ACTIVE",
    "message_key": "error.round_not_active",
    "retryable": false,
    "request_id": "uuid"
  }
}
~~~

Required common error codes:

~~~text
UNAUTHENTICATED
APP_CHECK_FAILED
ACCOUNT_SUSPENDED
ACCOUNT_DELETION_PENDING
RATE_LIMITED
IDEMPOTENCY_KEY_REUSED
INVALID_REQUEST
NOT_FOUND
FORBIDDEN
CONFLICT
ACTIVE_RUNTIME_CONFLICT
QUEUE_TICKET_NOT_ACTIVE
MATCH_NOT_FOUND
NOT_MATCH_PARTICIPANT
ROUND_NOT_ACTIVE
ROUND_EXPIRED
ANSWER_ALREADY_SUBMITTED
INVALID_OPTION
REACTION_ALREADY_USED
MATCH_SETTLEMENT_PENDING
PURCHASE_NOT_VERIFIED
REWARD_NOT_VERIFIED
~~~

---

# 20. CLOUD TASKS AND ROUND RESOLUTION

## 20.1 Principle

Cloud Tasks is durable and at-least-once. A task may be delayed, retried, duplicated, or dispatched out of the desired game-time order. Therefore:

- Task dispatch time is never an authoritative answer or bot timestamp.
- Every task handler calls the same idempotent resolver.
- Any answer or sync request also reconciles due events before applying a new action.
- Clients can trigger a bounded fallback sync; client sync has no authority by itself.

## 20.2 Queue layout

Provision queue families sharded by live match shard:

~~~text
round-recovery-00 .. round-recovery-15
round-start-00    .. round-start-15
bot-winner-00     .. bot-winner-15
settlement-00     .. settlement-15
cleanup-00        .. cleanup-15
~~~

Queue choice:

~~~text
queue_suffix = match.rtdb_shard_id suffix
~~~

Configure each queue with a conservative tested dispatch rate and concurrency. Do not deploy with a combined expected sustained task rate greater than 50% of configured capacity. The initial production configuration must be tested against dense-human and worst-bot-fill scenarios before launch.

Task payload:

~~~json
{
  "schema_version": 1,
  "task_kind": "ROUND_RECOVERY",
  "match_id": "match_uuid",
  "rtdb_shard_id": "live-07",
  "round_id": "round_uuid",
  "expected_state_version": 42,
  "idempotency_key": "hashed-task-id"
}
~~~

Task names use a non-sequential hash prefix and include match ID, round ID, and action kind. They must be unique for the task retention window.

The expected_state_version in a task is diagnostic and helps detect stale work. A resolver must not no-op merely because a reaction or wrong-answer event incremented state_version while the same round remains current. Round ID and authoritative state determine whether work is still due.

## 20.3 Scheduled events

At start of every round:

1. Create the complete server-only current-round state and bot plan.
2. Commit it atomically with the public/player-private round projection.
3. Publish ROUND_LOADING with next_server_event_at_ms = starts_at_ms.
4. Schedule one ROUND_START task at starts_at_ms + 50 ms.
5. Schedule one ROUND_RECOVERY task at ends_at_ms + 250 ms.
6. For Quick Battle only, if any bot has a planned correct response before end, schedule at most one BOT_WINNER task for the earliest planned correct response.

There is never one Cloud Task per bot wrong answer. Survival has no early bot winner task because correctness remains hidden until resolution.

Whenever a round transaction enters ROUND_REVEAL or ROUND_RESOLVE:

1. Set reveal_ends_at_ms using mode configuration.
2. Set next_server_event_at_ms = reveal_ends_at_ms.
3. Schedule one ROUND_ADVANCE task on the matching round-recovery queue at reveal_ends_at_ms + 50 ms.
4. The ROUND_ADVANCE handler calls the same resolver. It creates the next round or moves the match into FINISHED_PENDING_SETTLEMENT.

## 20.4 Resolver algorithm

All of these call the same function:

~~~text
resolve_round_if_due(match_id, round_id, caller_context)
~~~

Callers:

- Internal ROUND_RECOVERY task.
- Internal ROUND_START task.
- Internal BOT_WINNER task.
- Answer endpoint before accepting a human answer.
- Match sync endpoint.
- Recovery/settlement worker when it discovers an expired state.

Inside one canonical match-root transaction:

1. Load current state.
2. If round ID/state is no longer current, return a safe no-op.
3. If state is ROUND_LOADING and starts_at_ms is due, transition to ROUND_ACTIVE and publish next_server_event_at_ms as the earlier of planned correct bot time and ends_at_ms.
4. If a planned correct bot action is due and no winner exists, assign the bot winner using its precommitted planned timestamp.
5. If the round is expired and no Quick winner exists, close it or resolve Survival.
6. If state is ROUND_REVEAL or ROUND_RESOLVE and reveal_ends_at_ms is due, create the next planned round or move to FINISHED_PENDING_SETTLEMENT.
7. Apply correct answer reveal, score, elimination, event, next-state information, and state-version increment atomically.
8. Return the committed state transition.

After the transaction commits, enqueue any next round/recovery/settlement work required by the new state. If enqueue fails, a later sync/recovery worker discovers the missing scheduled action from canonical state and safely creates it.

## 20.5 Client resolver fallback

The public state contains:

- next_server_event_at_ms.
- designated_resolver_uid.
- state_version.

Normal behaviour:

1. Cloud Task resolves the event.
2. At event time + 250 ms, the designated active human client calls POST /v1/matches/{match_id}/sync if it still observes the old state version.
3. At event time + 750 ms, any active human client may issue one fallback sync if state is still stale.
4. Sync is rate-limited to one request per user/event and is safe to repeat.

The designated resolver is deterministic:

~~~text
lowest HMAC(server_resolver_key, match_id + ":" + round_id + ":" + eligible_human_uid)
~~~

It receives no authority or special information. It merely reduces normal fallback traffic. If it is offline, any other eligible human safely resolves the stale state.

## 20.6 Cloud Scheduler

Cloud Scheduler is only for low-frequency maintenance. It must never control a live 11-second game round.

Scheduled maintenance examples:

- Manifest rebuild/health validation.
- Question-stat aggregation.
- Purchase/revocation reconciliation.
- Backup/export triggers.
- Expired ticket/reward/live-match sweep.
- Monitoring/alert integrity checks.

---

# 21. MATCHMAKING

Matchmaking state never lives only in Cloud Run memory.

## 21.1 Inputs

Matchmaking considers:

1. Mode.
2. Question language.
3. Serving region.
4. Latency band.
5. MMR band.
6. Existing block relationships.
7. Queue wait time.

Priority:

~~~text
mode + language + region
-> latency compatibility
-> MMR compatibility
-> queue wait
-> bot fill
~~~

Never widen across region or latency band. Widen MMR only.

## 21.2 Ping measurement

Before entering public matchmaking:

- Client sends 5–7 lightweight authenticated ping requests.
- Backend records server receive/respond time; client reports median RTT only for grouping/diagnostics.
- Use client median RTT to choose a band:

~~~text
0–60 ms
61–120 ms
121–200 ms
201+ ms
~~~

- Client clock and client RTT never determine answer winner or score.
- Re-measure after material network change or every 15 minutes while app remains active.

## 21.3 Queue ticket lifecycle

Join flow:

1. Backend validates runtime state is IDLE.
2. In a Firestore transaction, create a ticket and set user_runtime to QUEUED.
3. Attempt immediate compatible-human match formation.
4. Return ticket ID, human_fill_at_ms, and status polling deadline.

Ticket values:

~~~text
Quick Battle human_fill_at_ms = created_at + 3,000 ms
Survival human_fill_at_ms     = created_at + 5,000 ms
ticket expiry                 = created_at + 60,000 ms
~~~

The client calls matchmaking status at human_fill_at_ms. That request is the normal server trigger for bot fill. A queued offline client is not silently started into a bot match; its ticket expires.

Join/leave/status rules:

- Joining with an existing active ticket returns that ticket idempotently.
- Leave transitions only QUEUED -> CANCELLED. A CLAIMED or MATCHED ticket returns the corresponding match/party state rather than deleting it.
- A server transaction claims all roster tickets together, verifies their runtime locks, assigns a claim ID, then creates the match index and updates each runtime state to MATCH_ACTIVE.
- If any candidate fails validation, the claim transaction retries with another candidate or releases the claim.
- Claim expiry recovery returns stale CLAIMED tickets to QUEUED only when no match index exists.
- No player may belong to more than one queue, party, or active match.

## 21.4 Quick Battle queue widening

Default:

~~~text
0–1.5 seconds: initial MMR range and same latency band
1.5–3.0 seconds: wider MMR range and same latency band
at 3.0 seconds: form with available compatible humans, fill remaining slots with bots
~~~

## 21.5 Survival queue

Default:

~~~text
0–5.0 seconds: gather up to 10 compatible humans
at 5.0 seconds: form with compatible humans, fill remaining slots with bots
~~~

## 21.6 Blocking

- Matching query excludes known blocked pairs where feasible.
- The roster-claim transaction rechecks blocks before final creation.
- If a race reveals a newly created block after match creation, do not cancel a competitive match mid-round. Hide reactions/interactions between the pair and prevent future party/social interaction.

## 21.7 Formation algorithm

For a public ticket:

1. Derive partition key from mode, language, region, and latency band.
2. Query the earliest bounded set of QUEUED tickets in that partition.
3. Filter expired, runtime-inconsistent, blocked, suspended, and already-claimed candidates.
4. Apply initial or widened MMR range according to the oldest candidate’s wait time.
5. Prefer the oldest compatible candidates, then smallest MMR distance.
6. If roster target is reached, atomically claim the roster.
7. If the caller has reached human_fill_at_ms, claim all currently compatible humans up to roster target and fill remaining slots with bots.
8. If no match forms, return QUEUED with the next safe status retry time.

The roster-claim Firestore transaction:

- Re-reads every selected ticket and user_runtime document.
- Requires ticket state QUEUED and runtime state QUEUED for every human.
- Writes one claim ID to every ticket.
- Creates match_index with assigned RTDB shard.
- Updates every user_runtime to MATCH_ACTIVE.
- Marks tickets MATCHED with match ID.

If any precondition fails, retry candidate selection. Never create an in-memory roster without durable claim state.

---

# 22. ROUND SYNCHRONISATION AND FAIRNESS

## 22.1 Round start

At round creation, backend publishes:

~~~text
round_id
question payload for current round only
starts_at_ms
ends_at_ms
next_server_event_at_ms
state_version
~~~

Default lead:

~~~text
round_starts_at_ms = server_now_ms + 2,000 ms
~~~

This gives clients time to receive and render. A client that renders late does not alter authoritative timing.

## 22.2 Media readiness

- Current-round media uses a signed URL that expires shortly after the relevant round/reveal window.
- Client starts download immediately.
- Client reports image-ready telemetry only; this is non-authoritative.
- Image-dependent questions need a confirmed available asset before round publication.
- If the client fails to load a non-essential image, it renders a stable fallback without moving answer controls.

## 22.3 Authoritative answer sequence

POST answer processing:

1. Verify Firebase token, App Check, account state, match pointer, shard, and participant eligibility.
2. Record backend server receipt timestamp.
3. Run resolver to process any due bot/round event before the human answer.
4. In one canonical match-root transaction, validate current state, round ID, option set, deadline, one-answer rule, and idempotency.
5. Apply wrong lock/penalty or winner/reveal transition.
6. Return committed result and current state version.

An answer after ends_at_ms is rejected. An answer that reaches the backend after a due precommitted bot winner is rejected as ROUND_NOT_ACTIVE after reconciliation.

## 22.4 No latency compensation

- There is no client-reported latency compensation.
- Fairness comes from same region, latency-band matchmaking, start lead time, small payloads, server authority, and measurement.
- Monitor client-to-server and server-to-RTDB latency by region/band.
- If a latency band fails fairness or completion targets, restrict public ranked matchmaking in that band rather than secretly changing scores.

---

# 23. BOT ENGINE

Bots exist to reduce queue wait during low liquidity. They are not Firebase Auth users and do not create client/database connections.

## 23.1 Bot identity and disclosure

Each bot has:

- bot_id.
- Reserved username.
- Curated avatar.
- Skill/MMR profile.
- Reaction profile.

Rules:

- Bot usernames are reserved in the same registry as human usernames.
- A bot roster item carries a subtle but unambiguous CPU/AI badge.
- Terms/Help clearly disclose that matches may contain computer-controlled opponents to reduce wait time.
- Never claim a bot-filled match contains all real humans.

## 23.2 Accuracy profiles

Default accuracy matrix:

| Bot profile | Easy | Medium | Hard |
|---|---:|---:|---:|
| Beginner | 70% | 45% | 20% |
| Normal | 85% | 65% | 40% |
| Strong | 94% | 80% | 60% |
| Expert | 98% | 91% | 78% |

Tune only from server configuration and production data.

## 23.3 Precommit

Before current-round public payload is committed, backend computes server-only bot plans:

~~~text
will_answer
will_be_correct
selected_concept_id
response_at_ms
optional_reaction_id
plan_commit_hash
~~~

Plan seed:

~~~text
HMAC(bot_plan_secret_version,
     match_id + ":" + round_id + ":" + bot_id + ":" + question_version)
~~~

Rules:

- The plan is immutable after round public publication.
- Bot response time comes from a realistic configured distribution based on skill and difficulty.
- Do not create consistently impossible sub-second response times.
- A bot plan never changes because a human is winning or losing.
- A bot chooses conceptual option IDs, never screen positions.
- Bot plan/audit data is retained server-only for dispute investigation.

## 23.4 Task minimisation

- Quick Battle schedules only the earliest planned **correct** bot winner for a round.
- Incorrect bot attempts are resolved internally at round end unless a future product requirement needs their public timing.
- Survival schedules no early bot answer task.
- Human answer endpoints reconcile due bot winners before accepting a human answer.

## 23.5 Bot analytics

Bots are excluded from:

- DAU/MAU.
- Retention.
- Human question accuracy.
- Human response time.
- Human ad revenue.
- Human-only match rate.

Track:

~~~text
human_slots
bot_slots
human_only_match_rate
average_bots_per_match
ranked_eligible_match_rate
~~~

---

# 24. MATCH STATE MACHINES

## 24.1 Quick Battle state machine

The canonical field **state** is the lifecycle/round state. **match_phase** is a separate field. Quick Battle phases are QUICK_NORMAL and QUICK_SUDDEN_DEATH.

| State | Entry action | Allowed client action | Exit condition |
|---|---|---|---|
| CREATED | Match index created | None | Roster claimed |
| WAITING_FOR_PLAYERS | Party/public roster collects | Party accept/leave only | Roster complete or fill time |
| PREPARING | Select questions, shard, MMR snapshot, bots | None | Current round created |
| ROUND_LOADING | Publish current question with 2s lead | Read/sync only | starts_at_ms reached |
| ROUND_ACTIVE | Accept answer/reaction | Answer, reaction, sync | Correct winner, bot winner, or deadline |
| ROUND_REVEAL | Publish answer/outcome | Reaction, sync | reveal timer ends |
| NEXT_ROUND | Create next planned question | Sync only | Next ROUND_LOADING |
| FINISHED_PENDING_SETTLEMENT | Final results fixed in live state | Read/sync only | Settlement succeeds |
| FINISHED | Compact final result available | Rematch/leave | Retention expiry |
| CANCELLED | Safe cancellation result | Read/leave | Retention expiry |
| EXPIRED | Live root may be removed | None | Cleanup |

Default reveal duration: 2,500 ms.

When normal Question 10 has a first-place score tie, set match_phase = QUICK_SUDDEN_DEATH. The ensuing Sudden Death questions still move through ROUND_LOADING, ROUND_ACTIVE, and ROUND_REVEAL.

## 24.2 Survival state machine

Survival phases are SURVIVAL_NORMAL, SURVIVAL_RESCUE, and SURVIVAL_TIEBREAK. Rescue and tiebreak are question kinds/phases, not additional exclusive values of state.

| State | Entry action | Allowed client action | Exit condition |
|---|---|---|---|
| CREATED / WAITING_FOR_PLAYERS / PREPARING | Same contract as Quick Battle | Queue/party actions as appropriate | Round prepared |
| ROUND_LOADING | Publish current question with lead | Read/sync only | starts_at_ms reached |
| ROUND_ACTIVE | Collect hidden answers | Answer, reaction, sync | deadline |
| ROUND_RESOLVE | Reveal answer/survivors/eliminations | Reaction, sync | resolution calculated |
| FINISHED_PENDING_SETTLEMENT / FINISHED / CANCELLED / EXPIRED | Same semantic contract as Quick Battle | As applicable | Settlement/cleanup |

Default Survival reveal duration: 3,000 ms.

## 24.3 State invariants

- Only backend can transition states.
- Every transition increments state_version.
- Every transition records state, triggering action, timestamp, and idempotency source in authoritative audit log.
- A stale task/action must safely no-op if its round ID is no longer current or its action is no longer due. State-version change alone is not sufficient reason to no-op.
- CANCELLED never awards MMR, ranked weekly XP, streak, crown, or rewarded-ad bonus. Technical compensation XP may be granted only by a separately configured, audited rule.

---

# 25. DISCONNECT, BACKGROUND, AND ABANDONMENT

## 25.1 Quick Battle

- Temporary disconnect does not pause a match.
- Missed question receives 0 if no answer submitted.
- Reconnect can restore the current match while live state exists.
- Completed questions are never replayed.
- Explicit Leave after match start records voluntary abandonment.
- Ranked-eligible abandonment is a loss for MMR/streak placement.
- No new human enters mid-match.
- Do not silently replace a disconnected human under that person’s username with a bot.

## 25.2 Survival

- Disconnected active player who fails to answer is treated by normal no-answer elimination.
- Reconnecting after elimination allows spectator mode only while live state remains.
- No re-entry.

## 25.3 Crash and recovery

- Client persists active match ID, shard selector, last public state version, and last round ID locally.
- On launch/foreground, bootstrap returns active match pointer and client reattaches listeners.
- Do not immediately show an interstitial after a crash/recovery flow.
- Record crash/reconnect telemetry.

---

# 26. QUESTION SELECTION ALGORITHM

## 26.1 Quick Battle

Before a Quick Battle begins, server preselects:

- Ten normal questions.
- At least five reserve Sudden Death/replacement questions.

Questions remain only in authoritative state until their round begins.

## 26.2 Survival

Before Survival begins, preselect:

- At least 30 candidate questions.
- At least ten reserves.

If the reserve threshold is reached, backend loads another server-only batch in the background. No future question reaches public state.

## 26.3 Candidate constraints

Candidate must satisfy:

~~~text
ACTIVE
verified
competitive_enabled
global_relevance_score >= 4
verified translation for match language
not expired
not quarantined
not already used in match
not in recent-human exposure union when viable
mode appropriate
media valid if media is required
~~~

Selection never loosens answer quality, language verification, or quarantine status. It may only relax exposure exclusion using the documented fallback ladder.

---

# 27. API DESIGN

All APIs are versioned under /v1. Authenticate with Firebase ID token and require App Check on protected mobile routes.

## 27.1 Session and profile

~~~text
POST   /v1/session/bootstrap
GET    /v1/ping
GET    /v1/profile
POST   /v1/profile/username
PATCH  /v1/profile/avatar
POST   /v1/profile/username/change
DELETE /v1/account
~~~

## 27.2 Catalog

~~~text
GET /v1/avatars
GET /v1/reactions
GET /v1/categories
GET /v1/client-config
~~~

## 27.3 Matchmaking

~~~text
POST   /v1/matchmaking/quick/join
DELETE /v1/matchmaking/quick/leave
POST   /v1/matchmaking/survival/join
DELETE /v1/matchmaking/survival/leave
GET    /v1/matchmaking/status
~~~

## 27.4 Match actions

~~~text
GET   /v1/matches/{match_id}
POST  /v1/matches/{match_id}/answer
POST  /v1/matches/{match_id}/reaction
POST  /v1/matches/{match_id}/leave
POST  /v1/matches/{match_id}/sync
POST  /v1/matches/{match_id}/question-report
~~~

Answer request:

~~~json
{
  "round_id": "round_uuid",
  "option_id": "concept_id",
  "request_id": "uuid",
  "client_diagnostics": {
    "displayed_at_monotonic_ms": 0,
    "tap_at_monotonic_ms": 0
  }
}
~~~

Client diagnostics are debugging-only and never authoritative.

## 27.5 Friends, party, and rematch

~~~text
GET    /v1/friends
GET    /v1/users/search?username=
POST   /v1/friends/requests
POST   /v1/friends/requests/{id}/accept
POST   /v1/friends/requests/{id}/decline
DELETE /v1/friends/{uid}
POST   /v1/blocks/{uid}
DELETE /v1/blocks/{uid}
POST   /v1/player-reports

POST   /v1/challenges
POST   /v1/challenges/{id}/accept
POST   /v1/parties/{id}/leave
POST   /v1/parties/{id}/start
POST   /v1/matches/{id}/rematch
POST   /v1/rematches/{id}/accept
~~~

## 27.6 Progression and purchase

~~~text
GET   /v1/missions/daily
GET   /v1/missions/weekly
POST  /v1/missions/{id}/claim
GET   /v1/leaderboards/weekly
GET   /v1/league
GET   /v1/category-stats

POST  /v1/purchases/verify/google
POST  /v1/purchases/verify/apple
GET   /v1/purchases/entitlements
POST  /v1/rewards/offers/{match_id}/start
~~~

## 27.7 Internal endpoints

~~~text
POST /internal/tasks/round-start
POST /internal/tasks/round-recovery
POST /internal/tasks/bot-winner
POST /internal/tasks/settlement
POST /internal/tasks/cleanup
POST /internal/ads/admob-ssv
POST /internal/purchases/google-rtdn
POST /internal/purchases/apple-notifications
~~~

Internal endpoints reject normal user tokens and require their documented service authentication/signature validation.

# 28. SECURITY AND ABUSE PREVENTION

## 28.1 Server authority

Client never decides:

- Correct answer.
- Winner.
- Score.
- XP.
- MMR, league, placement, streak, or crown.
- Mission completion.
- Purchase entitlement.
- Rewarded-ad grant.
- Bot plan/outcome.
- Question selection.
- Match state transition.

## 28.1a Production ingress

Production Cloud Run uses **internal-and-cloud-load-balancing** ingress.

- Mobile internet traffic reaches Cloud Run only through the external HTTPS Load Balancer and Cloud Armor.
- Direct public internet requests to the default Cloud Run URL are blocked by ingress.
- Keep the default Cloud Run URL available for same-project Cloud Tasks, Cloud Scheduler, Pub/Sub, and monitored internal calls where required; protect those internal routes with OIDC/service authentication in addition to ingress.
- Mobile API routes remain application-authenticated with Firebase ID token and App Check. Cloud Run IAM/ingress configuration must not replace those application checks.
- Validate this complete routing path in stage before production rollout.

## 28.2 Replay protection

Every answer validates:

- Firebase UID equals an eligible human participant.
- Active match pointer equals match ID.
- Request shard equals match index shard.
- Match state is answerable.
- Round ID equals authoritative current round.
- Option belongs to the caller’s current player-private option set.
- Current server time is before ends_at_ms.
- Caller has not already submitted an answer this round.
- Request ID/idempotency key is not improperly reused.

The canonical match transaction stores the accepted answer or safe duplicate response. A second answer with a new request ID returns ANSWER_ALREADY_SUBMITTED.

## 28.3 Rate limits

Use two layers:

1. **Cloud Armor / load-balancer controls:** IP/network-level abuse, malformed traffic, volumetric limits, and known bad patterns.
2. **Backend logical limits:** UID, match, device-attestation context, and endpoint-specific limits.

Default logical limits:

| Action | Limit |
|---|---|
| Answer | One accepted attempt per player/round; maximum five requests per 15 seconds including safe retries |
| Reaction | One per player/round |
| Queue join | Four per minute |
| Queue leave | Six per minute |
| Username search | 20 per minute |
| Friend request | 20 per day |
| Player report | 10 per day |
| Username change | One per 30 days |
| Reward offer start | One per settled match |

Rate-limit state is server-owned and distributed; never use per-instance memory as the sole production limiter.

## 28.4 Anti-cheat risk score

Track a non-public risk score from:

- Impossible response-time distribution.
- Abnormally high accuracy combined with unusually low accepted response times.
- Repeated malformed/stale requests.
- App Check failures.
- Device/account creation abuse.
- Queue join/leave manipulation.
- Purchase/reward callback anomalies.

Rules:

- Do not permanently ban from one anomaly.
- Increase risk, preserve evidence, and apply graduated restrictions.
- Possible sanctions: reduced queue access, ranked restriction, forced rename, temporary suspension, permanent ban.
- Human moderation remains available for irreversible decisions.

## 28.5 Secrets, keys, and IAM

- Store secrets in Secret Manager only.
- Never commit service-account JSON, model keys, IAP keys, payment secrets, HMAC keys, or admin credentials.
- HMAC keys have explicit key ID/version and rotation plan.
- Backend service accounts receive least privilege.
- No service account receives Project Owner.
- Task service account may invoke only documented internal task routes.
- Admin claim assignment occurs only through a protected backend/admin process.
- MFA is mandatory for admin accounts.

## 28.6 Logging

Do not log:

- Correct answer concept IDs.
- Full answer payload where not needed.
- Auth tokens, App Check tokens, purchase tokens, signed media URLs, or secrets.
- Full private profile information.

Structured logs include request ID, match ID, shard ID, action, state version, latency, outcome code, and safe pseudonymous UID reference.

---

# 29. USER-GENERATED CONTENT AND MODERATION

Even without free chat, usernames and curated interaction can require moderation.

Required:

- Username filtering and reserved-name controls.
- Player report.
- Block.
- Admin moderation queue.
- Rename-required sanction.
- Temporary suspension.
- Permanent ban.
- Audit log with actor, reason code, timestamp, and reversible/irreversible status.

Report reasons:

- Offensive username.
- Impersonation.
- Harassment through allowed interactions.
- Suspected cheating.
- Other predefined reason.

No public free-text user content exists at launch. Do not add user-uploaded avatar, chat, clan name, or user question authoring without a new moderation design.

---

# 30. ACCOUNT DELETION, PRIVACY, AND RETENTION

## 30.1 Account deletion

Settings includes **Delete Shared Synova Account**.

Flow:

1. User confirms clear cross-product deletion warning.
2. Require recent reauthentication where the provider requires it.
3. Backend marks user runtime as DELETION_PENDING and stops queue/match entry.
4. If the user has an active match, allow it to settle or cancel safely; never leave a live authoritative match orphaned.
5. Remove/anonymise personal profile, friends, requests, blocks where appropriate, device metadata, notification tokens, private settings, and product-specific personal records.
6. Delete Firebase Auth user.
7. Anonymise historical match records while retaining non-identifying aggregate game statistics where lawful.
8. Keep only a minimal hashed username reservation for 30 days, then release it.
9. Keep backup copies only under documented backup-retention policy and do not restore deleted personal data into active systems.

Provide an external web deletion path for store compliance.

## 30.2 Privacy principles

- Do not store precise location unless a later explicit feature and consent require it.
- Do not store exact DOB solely for 13+ gate.
- Do not expose country leaderboard/location by inference.
- Keep raw operational logs for 30 days by default; retain security/audit evidence only as long as necessary under the published policy.
- For EEA/UK/Switzerland advertising, use Google UMP / Privacy & Messaging consent flow before personalised-ad treatment.
- Maintain a data inventory and privacy-policy mapping before soft launch.

---

# 31. MONETIZATION

## 31.1 Interstitial policy

Ad-supported result flow:

~~~text
MATCH RESULT SHOWN
-> optional rewarded offer
-> eligible interstitial
-> Play Again / Home
~~~

Rules:

- Never show interstitial during a question, before result is visible, during reconnect recovery, or deceptively after Play Again.
- Aim for one interstitial opportunity per completed match.
- Enforce minimum 45 seconds since previous displayed interstitial.
- Ad availability must never block navigation or delay result flow.
- Ad-free entitlement skips interstitial opportunities.
- Interstitial state is analytics/business logic only; it never alters match authority.

## 31.2 Rewarded video

At a settled result, eligible player may choose:

~~~text
Watch video -> 2x base match XP
~~~

Secure flow:

1. Client requests POST /v1/rewards/offers/{match_id}/start.
2. Backend verifies settled match, UID, daily cap, no existing grant, and creates a 15-minute one-time reward offer.
3. Backend returns signed compact custom data containing offer ID, UID hash, match ID, expiry, and nonce.
4. Client passes that custom data to the AdMob rewarded SDK server-side verification configuration.
5. Internal AdMob SSV endpoint validates the provider signature, offer state, expiry, nonce, UID/match binding, and idempotency.
6. In one transaction, mark reward grant complete and add reward bonus XP.

Rules:

- Client reward callback alone never grants XP.
- A duplicate/malformed/late SSV callback is a safe no-op or error.
- A reward offer may be granted once only.
- Rewarded completion satisfies that match’s interstitial opportunity.
- Rewarded video never changes score, placement, MMR, survival life, answer, winner, mission count, or ranked weekly XP.

## 31.3 Remove Ads Forever

Product:

~~~text
Remove Ads Forever
Base price: USD 4.99
Type: non-consumable one-time purchase
~~~

Rules:

- Store pricing is localized by Google/Apple.
- Entitlement is server-verified and associated with global UID according to valid store-account restoration policy.
- Restore purchase works after login.
- A purchase in PENDING state grants no entitlement.
- Refund, revocation, family-share revocation, cancellation, and reactivation are processed by verified store server notifications/reconciliation.
- Ad-free users may voluntarily watch rewarded ads; doing so is never required.

## 31.4 Google Play purchase lifecycle

- Client sends purchase token only to backend verification endpoint.
- Backend verifies through Google Play Developer API.
- Backend records transaction idempotently, grants entitlement only after valid purchased state, and acknowledges according to Google policy.
- Google RTDN arrives through a protected Pub/Sub subscription to internal backend handler.
- RTDN handler fetches current purchase state from Google before changing entitlement.
- Scheduled reconciliation detects missed notifications and stale entitlement state.

## 31.5 Apple purchase lifecycle

- Client sends StoreKit signed transaction/JWS only to backend verification endpoint.
- Backend verifies signing and product identity.
- App Store Server Notifications V2 are received at a protected endpoint and signature-verified.
- Refund/revocation/family-share changes update entitlement idempotently.
- Scheduled reconciliation is retained for missed notification recovery.

## 31.6 Ad preload

- Preload the next interstitial during active gameplay where platform policy permits.
- Never block gameplay or result display for ad preload.
- Log load, no-fill, show, dismiss, and revenue metadata where available without storing unnecessary personal data.

---

# 32. SERVER CONFIGURATION MODEL

Server-critical rules live in server-only Firestore configuration, cached by backend with version checking. Firebase Remote Config is for client presentation/rollout only.

## 32.1 Remote Config allowed uses

Examples:

~~~text
show_category_queues
show_rewarded_xp
new_home_layout
reaction_animation_duration
feature_survival_enabled
client_ad_presentation_interval
~~~

Remote Config is never secure authority.

## 32.2 Server configuration

Example:

~~~json
{
  "schema_version": 1,
  "config_version": 7,
  "quick": {
    "normal_questions": 10,
    "seconds": 11,
    "reveal_ms": 2500,
    "wrong_penalty": -4,
    "no_answer_penalty": 0,
    "bot_fill_ms": 3000,
    "sudden_death_unresolved_cap": 5
  },
  "survival": {
    "seconds": 11,
    "reveal_ms": 3000,
    "bot_fill_ms": 5000,
    "unresolved_round_cap": 3,
    "rescue_seconds": 15
  },
  "matchmaking": {
    "ping_bands_ms": [60, 120, 200],
    "initial_mmr_range": 100,
    "widened_mmr_range": 250
  },
  "economy": {
    "rewarded_xp_daily_cap": 5
  }
}
~~~

Every match stores an immutable snapshot of relevant configuration version and values in authoritative state and match history.

---

# 33. ANALYTICS, QUESTION STATS, AND LEADERBOARDS

## 33.1 Product analytics

Use Firebase Analytics for product-level events, not every low-level answer event.

Recommended events:

~~~text
onboarding_complete
username_created
matchmaking_started
match_started
match_completed
match_cancelled
quick_win
survival_win
survival_eliminated
rematch_requested
friend_request_sent
friend_challenge_sent
reaction_used
mission_completed
ad_impression
rewarded_completed
remove_ads_purchase
account_deleted
~~~

Detailed answer telemetry belongs in backend aggregation with privacy-aware retention.

## 33.2 Question statistics at scale

Do not increment one hot Firestore question document for every answer.

Use sharded counters:

~~~text
question_stats_shards/{question_version_language_mode}/shards/{0..31}
~~~

Randomly choose a shard for human-stat writes. Periodically aggregate into summary documents.

Track:

~~~text
shown
attempted
correct
wrong
no_answer
censored_by_early_quick_winner
sum_response_ms
report_count
~~~

Bots never increment human-stat counters.

## 33.3 Leaderboard storage

One document per user/week:

~~~text
weekly_user_stats/{week_id}_{uid}
~~~

Fields:

~~~text
uid
week_id
ranked_weekly_xp
quick_ranked_wins
survival_ranked_crowns
league
tie_break_hash
~~~

Query with indexed pagination. Do not store a global leaderboard in one document.

---

# 34. MEDIA STORAGE AND NOTIFICATIONS

## 34.1 Storage security

Storage paths:

~~~text
questions/{question_group_id}/v{version}/main.webp
avatars/{avatar_id}.webp
badges/{badge_id}.webp
~~~

Rules:

- Raw question media is not publicly listable.
- Backend creates short-lived signed URLs only for active current-round question media.
- Future question paths/URLs never appear in client payloads.
- Curated public cosmetics may use public-read/CDN-safe paths because they do not reveal competitive content.
- Admin upload requires admin authorization and media metadata.
- Versioned question media is immutable and uses immutable cache headers.
- Never overwrite an existing versioned question image in place.

## 34.2 Notifications

Use FCM for:

- Friend request.
- Friend challenge.
- Challenge accepted.
- Weekly leaderboard ending.
- Mission reminder.
- League promotion/result.

Respect user notification preferences. Never send marketing or reminder notifications at a rate that feels spammy.

# 35. OBSERVABILITY AND OPERATIONS

## 35.1 Mobile observability

- Firebase Crashlytics.
- Firebase Analytics breadcrumbs.
- Match reconnect diagnostics.
- Non-authoritative round-render and media-ready telemetry.
- Ad/IAP failure telemetry without sensitive purchase payloads.

## 35.2 Backend observability

- Cloud Logging with structured JSON.
- Cloud Monitoring dashboards and alerts.
- Trace ID / request ID propagation.
- Match ID, shard ID, config version, state version, task kind, and safe outcome code in logs.

Monitor:

~~~text
answer endpoint p50 / p95 / p99
match sync p95
matchmaking wait p50 / p95
ping distribution by region/band
round late-render rate
image load p95
Cloud Run instances, CPU, memory, errors
RTDB writes, responses, bandwidth per shard
RTDB transaction retry rate per shard
Cloud Tasks queue delay, retry, duplicate-safe no-op rate
settlement latency/failure/retry rate
match cancellation rate
disconnect/reconnect rate
bot ratio
human-only and ranked-eligible match rates
ad fill, display, and reward-SSV rates
purchase verification/revocation events
question report rate
moderation and risk-score actions
~~~

## 35.3 Launch SLOs

For the supported primary region/bands:

~~~text
Answer API p95 < 250 ms
Answer API p99 < 500 ms
Client-observed state update p95 < 750 ms after accepted answer
Match creation p95 < 1 second after roster is claimed
Backend 5xx < 0.5%
No lost or double authoritative match settlement
No client-readable answer/future-question leak
~~~

These are validated load-test goals, not assumptions.

---

# 36. TARGET SCALE AND ADMISSION CONTROL

## 36.1 Capacity design

The live shard ring, task queues, and Cloud Run configuration must be measured under:

- 10,000 human clients in full Quick Battle rooms.
- 10,000 human clients in full Survival rooms.
- 10,000 human clients split by language/latency/MMR.
- 10,000 human clients each in a bot-filled minimum-human room.
- Synchronized answer bursts near round start, normal midpoint, and deadline.

Per-shard targets are set from real measurements. Initial production planning assumes:

~~~text
16 live shards
target average active rooms per shard <= 625 in the 10k-human worst-room model
target sustained RTDB write rate per shard <= 500 writes/second
task dispatch planning per queue <= 50% of configured tested capacity
~~~

If a load test cannot satisfy these values, do not raise public capacity. Increase shard count, reduce admission, reduce bot-event task count, or optimise state writes before claiming the next target.

## 36.2 Admission control

The backend must fail safely before an overloaded system damages active fairness.

- Track active room count and live-write/latency health by shard.
- Do not create new matches when the target shard ring or Cloud Run protection threshold is unhealthy.
- Return a user-safe retryable capacity response with bounded retry-after.
- Existing active matches have priority over new matchmaking.
- Never queue a player indefinitely to hide a capacity failure.
- Feature flags can disable Survival, category queues, new language activation, or rewarded offers independently during an incident.

## 36.3 Cloud Run scaling

- Cloud Run max instances, concurrency, CPU, memory, thread strategy, and relevant quotas are a single tested capacity unit.
- Default stage tuning is not production proof.
- Pre-warm enough min instances for anticipated event bursts only after cost/performance tests.
- Load-test failures caused by cold starts, queue backlog, or external service saturation block 10k approval.

---

# 37. MATCH SETTLEMENT AND PERSISTENCE

## 37.1 Finish protocol

At game end:

1. In the canonical RTDB match-root transaction, set final placements and transition to FINISHED_PENDING_SETTLEMENT.
2. Create/update the Firestore settlement ledger with stable settlement idempotency key.
3. Schedule a settlement task.
4. The settlement transaction applies all persistent user updates atomically where possible.
5. Mark settlement SETTLED.
6. Update each user_runtime from SETTLEMENT_PENDING to IDLE.
7. Set live match public state to FINISHED and enable rematch/result navigation.
8. Schedule live-state cleanup.

## 37.2 Settlement transaction

For all human participants, atomically or idempotently apply:

- Final placement and compact match history.
- Base XP.
- Reward offer eligibility state.
- MMR/league only if ranked-eligible.
- Streak/crown only if ranked-eligible.
- Ranked weekly XP only if ranked-eligible.
- Mission progress.
- Badge/frame progress.
- Recent shown qids.
- Question statistic write intents.
- User progression event with monotonic sequence.

Rules:

- Use one match settlement idempotency key.
- Never award XP/MMR twice.
- A user may not queue/rematch while that user’s settlement is pending.
- If settlement retry is necessary, recompute only from immutable final match result/config snapshot; never from current mutable profile data.
- If backend cannot settle after configured retry policy, keep the result visible as Finalising Results, alert operations, and preserve player runtime lock. Do not let an unsafely partial result create a second match.

## 37.3 Cancellation

Use CANCELLED only for unrecoverable technical failure before a trustworthy competitive final result exists.

- Cancelled matches award no MMR, league, ranked weekly XP, win streak, crown, or rewarded bonus.
- Record cancellation reason.
- A narrowly scoped server-configured participation compensation may exist, but must be idempotent, auditable, and cannot influence leaderboard/rank.

---

# 38. SYNOVA INTEGRATION

Synova uses the same question platform and shared identity/exposure service.

Synova request contract:

~~~text
mode = synova_curiosity
language
category filters
difficulty filters
global authenticated UID
~~~

Shared backend:

- Selects questions.
- Applies version/language/content quality requirements appropriate to the requested mode.
- Records actual question exposure.
- Records human answer statistics.
- Returns only safe current-session payloads.

Synova and Live Trivia do not share:

- XP.
- Levels.
- League/MMR.
- Friends.
- Match history.
- Missions.
- Ads/IAP.
- Game-specific achievements.

---

# 39. FRONTEND ARCHITECTURE — LIVE TRIVIA

Recommended Flutter structure:

~~~text
lib/
  app/
  routing/
  core/
    config/
    networking/
    firebase/
    analytics/
    errors/
    rtdb_shards/
  features/
    auth/
    onboarding/
    profile/
    home/
    matchmaking/
    quick_battle/
    survival/
    match_shared/
    reactions/
    friends/
    leaderboard/
    missions/
    achievements/
    purchases/
    settings/
    moderation/
  shared/
    models/
    widgets/
    localization/
~~~

Riverpod providers/notifiers own feature state. Widgets never contain authoritative game logic.

## 39.1 Client live-match responsibilities

Client:

- Uses match_index shard selector to connect to one active RTDB shard.
- Observes public projection plus its own player-private projection.
- Renders local visual countdown from server timestamps/offset.
- Submits one answer intent and renders server-confirmed result.
- Runs designated/fallback sync protocol only as documented.
- Detaches listeners on match end, leave, account deletion, or shard change.
- Stores last match pointer/state version for recovery.

Client must not:

- Calculate/commit winner, score, elimination, XP, MMR, or correct answer.
- Guess future question URLs.
- interpret UI countdown as authority.
- retain a valid signed question-media URL beyond its expiry.

## 39.2 App lifecycle

Handle:

- Foreground/background.
- Reconnect.
- RTDB listener reattach.
- Firebase ID token refresh.
- App Check refresh.
- Ad lifecycle.
- Incoming challenge deep link.
- Match settlement pending state.
- Account deletion pending state.

## 39.3 Match UI layout

Reserve stable visible regions for:

- Question image/text.
- Four answer options.
- Round timer.
- Four or ten player avatar/status items.
- Reaction bubble.
- Score or Survival status.

Reaction overlays may never obscure question/answers. Accessibility labels, dynamic font robustness, and tap target spacing are required.

---

# 40. TEST PLAN

## 40.1 Scoring unit tests

Must include:

~~~text
10.999 seconds remaining -> 10 points
10.000 seconds remaining -> 10 points
 9.999 seconds remaining ->  9 points
 1.001 seconds remaining ->  1 point
 0.100 seconds remaining ->  1 point
wrong human answer          -> -4
no answer                   ->  0
~~~

Also test:

- Duplicate request rejection/idempotent return.
- Late answer rejection.
- Invalid option rejection.
- Concurrent correct answers yield one winner.
- Due bot winner beats a later human request.
- Late/duplicate task cannot alter a resolved round.

## 40.2 Quick Battle tests

- Four humans.
- One human plus three bots.
- All bots except one human.
- Nobody correct.
- Multiple wrong then correct.
- Top-score tie.
- Two-player, three-player, and four-player Sudden Death.
- Sudden Death unresolved cap.
- Reconnect.
- Voluntary abandonment.
- Settlement/requeue/rematch ordering.

## 40.3 Survival tests

- Normal elimination.
- All submitted answers wrong.
- Some wrong, some no-answer, no correct.
- Nobody submits.
- Rescue round.
- Three consecutive unresolved rounds.
- Final tiebreak deterministic outcome.
- Last two both wrong.
- Single correct survivor.
- Disconnect elimination.
- Spectator behaviour.

## 40.4 Matchmaking tests

- Simultaneous join/leave.
- Duplicate join idempotency.
- Queue claim collision across Cloud Run instances.
- Ticket expiry.
- Bot fill at exact deadline.
- Block race at claim time.
- One user attempting second queue/party/match.
- Queue pressure/capacity response.

## 40.5 Bot tests

- Precommit hash remains unchanged after any human event.
- Accuracy distribution by difficulty.
- Response-time distribution.
- Earliest correct-bot event only.
- Human answer after earlier planned bot winner.
- Duplicate and delayed bot task.
- Bot analytics separation.

## 40.6 Security tests

- Client cannot read private answer.
- Client cannot read future question/image URL.
- Client cannot read another player’s option order.
- Client cannot write score/MMR/match state.
- Client cannot submit second answer/reaction.
- Nonparticipant cannot read a match.
- Spectator cannot read player-private data.
- App Check enforcement.
- Admin authorisation/MFA boundary.
- Username reservation race.
- Signed media expiry/access policy.
- Ad reward callback signature/nonce tests.
- Purchase callback/revocation tests.

## 40.7 Load tests

Use Locust or k6 plus a Firebase-aware test harness. Never simulate only smooth HTTP traffic.

Stages:

~~~text
100 concurrent human clients
1,000 concurrent human clients
5,000 concurrent human clients
10,000 concurrent human clients
burst above target
~~~

Required workloads:

- Dense Quick Battle.
- Dense Survival.
- Mixed latency/MMR/language.
- One-human-per-bot-filled-room worst case.
- Synchronized answer bursts near exact scoring boundaries.
- Sync fallback burst.
- Cloud Task delayed/duplicate injections.
- RTDB shard-loss/reconnect simulation.

Measure:

- Cloud Run p95/p99 and saturation.
- RTDB writes/responses/transaction retries by shard.
- Cloud Tasks dispatch delay/retry.
- Match correctness/winner race.
- Settlement correctness.
- Bandwidth.
- Error rate.
- Admission-control behaviour.

## 40.8 Failure and chaos tests

- Cloud Run instance restart during match.
- Duplicate Cloud Task.
- Delayed Cloud Task.
- RTDB reconnect.
- One unavailable RTDB shard.
- Firestore transient failure during settlement.
- Storage signed URL expiry/failure.
- Ad SDK failure.
- Rewarded SSV delayed/duplicate callback.
- IAP verification/revocation retry.
- App background at answer/round end.

---

# 41. DEPLOYMENT AND CI

Backend container:

- Reproducible build.
- Static checks, unit tests, integration tests, security-rule tests.
- Deploy dev automatically.
- Deploy stage, then run smoke tests and selected load test.
- Manual approval for production initially.

Use Cloud Build connected to GitHub. Do not rely on a large GitHub Actions minute budget for core deployment.

Before production deployment:

- Migration/release plan is checked.
- All RTDB shard rules deploy successfully.
- Server config is versioned and approved.
- Secret references exist in target project.
- Stage smoke tests pass.
- Rollback revision is known.

---

# 42. BACKUPS AND DISASTER RECOVERY

Question content is business-critical.

Back up:

- Question groups, translations, private answers, source metadata, and status history.
- Media assets and metadata.
- Server configuration.
- User profiles/relationships/entitlements as appropriate.
- Match history and settlement ledger as appropriate.

Rules:

- Live RTDB match state does not need long-term backup, but active-match incident diagnostics retain according to short operational policy.
- Backups are protected, access-controlled, encrypted, and subject to retention/deletion policy.
- Periodically test restore of question content and server configuration into an isolated environment.
- A restore must not resurrect a deleted user into active production without an explicit lawful recovery process.

---

# 43. IMPLEMENTATION PHASES

## Phase 0 — Foundation

Deliver:

- Dev/stage/prod Firebase/GCP projects.
- Primary-region placement decision and verified service availability.
- Cloud Run FastAPI skeleton.
- Secret Manager.
- Firebase Auth/App Check wiring.
- HTTPS load balancer and Cloud Armor baseline for production path.
- Firestore/Storage rules baseline.
- Two dev RTDB shards, four stage shards, sixteen production-shard infrastructure definitions.
- Emulator setup.
- Flutter skeleton.
- Crashlytics/Analytics.
- Basic CI.

Exit:

- Authenticated Flutter test user can call protected backend.
- App Check works in stage.
- No production database/storage rule is open.
- Client can select RTDB shard URL from a safe mock match index.

## Phase 1 — Shared Question Platform and Seed Content

Deliver:

- Category/subcategory schema.
- Question group, translation, private answer, media, versioning.
- Exposure service.
- Pool manifest generation.
- Minimal admin CRUD and validation.
- Content seed workflow.
- Minimum soft-launch inventory for the first enabled language before competitive external testing.

Exit:

- One verified question serves both Synova test client and Live Trivia test client without duplication.
- Correct answer is not directly readable by mobile client.
- Manifest does not contain answer key/future client media URLs.

## Phase 2 — Account, Profile, and Moderation Basics

Deliver:

- 13+ gate.
- Login.
- Global username registry.
- Avatar catalog.
- Username cooldown.
- Block/report.
- Shared account-deletion flow.
- User runtime lock.

Exit:

- Concurrent attempts cannot reserve one username.
- Offensive/reserved usernames reject.
- A user cannot create two active runtime states.
- Shared deletion warning and flow work end-to-end.

## Phase 3 — Live Match Substrate and Matchmaking

Deliver:

- Firestore queue tickets.
- Atomic roster claim.
- RTDB canonical match root on shard ring.
- Player-private/public rules.
- Round resolver and sync fallback.
- Task queue families.
- Match index/shard connection.
- Settlement ledger skeleton.

Exit:

- Two Cloud Run instances cannot double-match one player.
- A duplicate/delayed task is harmless.
- A client cannot read another player’s option order or authoritative state.

## Phase 4 — Quick Battle Core

Deliver:

- Four slots.
- Question selection.
- 11-second rounds.
- Answer API.
- Correct answer atomic winner.
- **Wrong answer -4; no answer 0.**
- Score/ranking.
- Sudden Death.
- Settlement/match history.

Initially test humans and deterministic test bots.

Exit:

- All scoring boundary tests pass.
- No double winner in stress race.
- Rematch cannot repeat a just-shown group because settlement was delayed.

## Phase 5 — Production Bot Engine

Deliver:

- Bot identity pool.
- Skill profiles.
- Precommitted plans/audit hash.
- Earliest correct-bot wake-up only.
- Bot-fill matchmaking.
- Disclosure/badge.
- Analytics separation.

Exit:

- Delayed/duplicate task cannot change an outcome incorrectly.
- Bot-heavy match does not change ranked systems unless human-opponent requirement is met.

## Phase 6 — Survival

Deliver:

- Ten-slot elimination state machine.
- Hidden correctness.
- All-wrong, rescue, no-answer, and final tiebreak rules.
- Spectator state.

Exit:

- All unresolved edge cases end deterministically.
- One winner always exists unless a technical cancellation occurs.

## Phase 7 — Social and Progression

Deliver:

- Friends, challenge, party, rematch.
- Reactions.
- XP/levels.
- MMR/leagues.
- Weekly leaderboard.
- Streak/crowns.
- Category stats.
- Badges/frames.
- Missions.

## Phase 8 — Monetization

Deliver:

- UMP consent.
- Interstitial policy.
- Rewarded offer/SSV/nonce flow.
- Remove Ads Forever.
- Google RTDN and Apple notification handlers.
- Store verification, restore, refund/revocation reconciliation.

## Phase 9 — Advanced Admin and Content Factory

Complete:

- AI batch generation.
- Semantic duplicate detection.
- Translation review.
- Media licensing workflow.
- Quarantine automation.
- Moderation panel.
- Pool health dashboard.

## Phase 10 — Scale and Security Hardening

Deliver:

- 10k human load tests including worst bot-fill topology.
- p95/p99 tuning.
- RTDB shard health/capacity validation.
- Cloud Run and Cloud Tasks tuning.
- App Check enforcement in production.
- Cloud Armor policy validation.
- Security-rule tests.
- Abuse monitoring.
- Backup/restore test.

## Phase 11 — Soft Launch

Start with limited geography/language cohort and hard admission cap.

Measure:

- D1/D7 retention.
- Games per DAU.
- Match completion.
- Quick vs Survival share.
- Bot ratio.
- Human-only/ranked-eligible rate.
- Matchmaking wait.
- Ad impressions/DAU and ARPDAU.
- Ad-free conversion.
- Rewarded opt-in/failure rate.
- Question report rate.
- Crash-free users.
- Shard/task/settlement health.

Scale acquisition only after these metrics and capacity tests remain stable.

---

# 44. NON-GOALS FOR INITIAL PRODUCT

Do not build initially:

- Free-text chat.
- User-uploaded avatars/photos.
- Clans/teams.
- Cash prizes.
- Paid Survival revive.
- Energy/ticket system.
- User-generated trivia publishing.
- Marketplace.
- Voice/video chat.
- AWS/EKS.
- Kubernetes.
- Kafka.
- Redis cluster.
- Custom WebSocket infrastructure.
- Separate microservice per feature.
- Cross-region first-answer competition.

---

# 45. FINAL ACCEPTANCE CHECKLIST

## Product

- Quick Battle rules exactly implemented: wrong answer -4, no answer 0.
- Survival normal/rescue/tiebreak rules exactly implemented.
- Sudden Death works and has unresolved cap.
- Unique global usernames and curated avatars work.
- Curated reaction one-per-round works.
- Friends/challenge/rematch work.
- XP, ranked systems, weekly leaderboard, streak, missions, badges work.
- Bot-heavy matches cannot distort ranked systems.

## Questions

- Shared question platform serves Synova and Live Trivia.
- Global relevance and 13+ quality filters work.
- Exactly nine approved categories; no Gaming category.
- Versioning/source/license/translation rules work.
- Recent-question avoidance records actually shown questions.
- Competitive verification/report/quarantine work.
- Language and category activation gates pass before public enablement.

## Security

- Correct answer/future question/future media URL never exposed early.
- App Check/Auth/server authority enforced.
- Canonical match transaction produces one winner.
- Client cannot read authoritative or another player-private state.
- RTDB shard rules pass.
- Storage signed delivery rules pass.
- Least-privilege IAM/Secret Manager used.
- Cloud Armor/backend rate limits applied.
- Account deletion, report, block, moderation work.

## Bots

- Reserved names/avatars.
- No Firebase user accounts.
- Precommitted immutable plans.
- Task delay/duplicate safe.
- Human analytics separation.
- Clear disclosure/badge.

## Monetization

- Result shown before ad.
- 45-second interstitial minimum.
- Rewarded SSV only; no client-only XP grant.
- Rewarded bonus excluded from ranked weekly XP/MMR/missions.
- Remove Ads entitlement server-verified/restorable/revocable.
- Google/Apple lifecycle handlers pass tests.
- UMP consent works.

## Scale

- All 10k-human required load scenarios pass.
- No matched-player duplication.
- Answer race stress passes.
- Task delayed/duplicate recovery passes.
- RTDB shard throughput/response health passes.
- Cloud Run capacity/quota configuration passes.
- Alerting and admission control configured.
- Backup restore tested.

## Store readiness

- 13+ positioning.
- Privacy Policy and Terms.
- Bot disclosure.
- In-app plus external web deletion path.
- Reporting/blocking.
- Ad consent.
- Correct store IAP configuration.

---

# 46. FINAL SYSTEM SUMMARY

~~~text
TWO APPS
Synova + Live Trivia
        |
        v
SHARED FIREBASE AUTH / GLOBAL IDENTITY
        |
        v
ONE FASTAPI CLOUD RUN BACKEND
        |
        +-------------------+------------------------+
        |                   |                        |
        v                   v                        v
FIRESTORE           RTDB SHARD RING            CLOUD STORAGE
persistent data     live canonical state        versioned WebP
questions/users     16 production shards        signed current media
queues/history      public/private projections
        |
        v
CLOUD TASKS
idempotent due-event recovery, settlement, cleanup

+ Analytics + Crashlytics + Remote Config + FCM
+ Cloud Armor + Secret Manager + Monitoring
+ AdMob + Store IAP lifecycle verification
~~~

The system deliberately remains one managed backend codebase and Firebase/GCP services. It does not need Kubernetes, Kafka, Redis clusters, or custom sockets. It does require disciplined server authority, native RTDB sharding, explicit settlement ordering, and task-recovery semantics to make a fast live trivia game correct at its stated target.

<!-- END OF SPECIFICATION -->
