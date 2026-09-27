# Playtest Feedback Implementation Plan (2026-09-27)

Product decisions from the first internal playtest. They supersede the matching parts of
`docs/spec/synova_live_trivia_development_spec_v1_1.md`.

## Decisions

| # | Decision |
|---|---|
| D1 | Answer window 15 s for Quick Battle and Survival normal rounds. Quick points = clamp(floor(remaining_s), 1, 15). |
| D2 | Wrong answer in Quick Battle: -6 (same 40% ratio to max points as the old -4/10). |
| D3 | Easier Quick Battle curve: 4 EASY / 4 MEDIUM / 2 HARD. Reserves: MEDIUM, MEDIUM, MEDIUM, HARD, HARD. |
| D4 | Survival opens with 3 guaranteed EASY rounds, then an easier count-based curve. |
| D5 | Reveal pause 3.5 s with a centred celebration: "<name> got it +N" for others, "You got it! +N" for self, private "Wrong -6" for self only. Wrong answers are never public. |
| D6 | Survival: eliminated players get a red X overlay; the eliminated player sees a clear banner. |
| D7 | No image questions. Curated image questions are rewritten as text, flag questions dropped, image UI removed from the client. Backend media support stays dormant. |
| D8 | Rules summary on the matchmaking screen; Home keeps the one-tap Play button, the Play tab is the mode chooser with rules. Guide numbers come from server config. |
| D9 | Bootstrap ranking: while active humans < 100, matches with bots are ranked-eligible and bots take part in leagues and weekly leaderboards. |
| D10 | Weekly cohort leagues: groups of 100 (bots fill), top 20 promote, bottom 20 relegate, Bronze never relegates. Bronze groups are hidden from users. Placement/Unranked removed. MMR stays for matchmaking only. |
| D11 | Rewarded XP removed. XP only from match performance. |
| D12 | Ad gate: after every 3 completed matches the next match requires an interstitial, preceded by a friendly "why ads" card. No fill / offline / no consent never blocks play. |
| D13 | Levels unlock cosmetics (frames/avatars) at milestones; profile shows the next unlock. |

## Phases

Each phase: feature branch -> tests (pytest, ruff, flutter analyze/test) -> PR into `Hakan-oltivra` -> merge ->
stage deploy (+ seed changes) -> AAB. Next phase starts without waiting.

### Phase 1 — Match experience (D1–D8)
1. Config: quick/survival `seconds=15`, quick `wrong_penalty=-6`, `reveal_ms=3500`; points cap derived from seconds.
2. Selector orders (D3); survival difficulty (D4).
3. Mobile celebration overlay + private wrong overlay (D5); survival X overlay (D6).
4. Remove image questions (D7): rewrite curated content as text under new keys, drop flags, retire old image
   groups in the stage database, remove image widget from the client.
5. Rules strip on FindingMatchScreen, Play tab as mode chooser, guide reads `max_points` from client config (D8).

### Phase 2 — Ranking (D9, D10)
1. Ranked eligibility bootstrap flag with active-human threshold (server config).
2. League groups: weekly cohort assignment (100 per group, bots fill), weekly XP per group, rollover job with
   promotion/relegation, hidden Bronze groups, league/group endpoints, remove placement/Unranked.
3. Bots accrue deterministic weekly XP so standings move realistically.
4. Mobile: league shown on Home/Profile, league screen with group standings and promotion/relegation zones.

### Phase 3 — Economy & progression (D11–D13)
1. Remove rewarded XP (backend routes/config and client UI).
2. Ad gate every 3 matches with pre-ad card and no-fill fallback.
3. Level milestone unlocks and "next unlock" UI.
