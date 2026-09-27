---
name: Live Trivia Visual Foundation
colors:
  surface: '#faf8ff'
  surface-dim: '#d4d9ee'
  surface-bright: '#faf8ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f3ff'
  surface-container: '#e9edff'
  surface-container-high: '#e2e7fd'
  surface-container-highest: '#dde2f7'
  on-surface: '#151b2a'
  on-surface-variant: '#3c4947'
  inverse-surface: '#2a3040'
  inverse-on-surface: '#edf0ff'
  outline: '#6c7a77'
  outline-variant: '#bbcac6'
  surface-tint: '#006b5f'
  primary: '#006b5f'
  on-primary: '#ffffff'
  primary-container: '#16b8a6'
  on-primary-container: '#00423b'
  inverse-primary: '#50dbc8'
  secondary: '#af2759'
  on-secondary: '#ffffff'
  secondary-container: '#ff6695'
  on-secondary-container: '#6a002f'
  tertiary: '#795900'
  on-tertiary: '#ffffff'
  tertiary-container: '#ce9d1d'
  on-tertiary-container: '#4c3700'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#71f8e4'
  primary-fixed-dim: '#50dbc8'
  on-primary-fixed: '#00201c'
  on-primary-fixed-variant: '#005048'
  secondary-fixed: '#ffd9e0'
  secondary-fixed-dim: '#ffb1c3'
  on-secondary-fixed: '#3f0019'
  on-secondary-fixed-variant: '#8e0441'
  tertiary-fixed: '#ffdf9e'
  tertiary-fixed-dim: '#f4bf40'
  on-tertiary-fixed: '#261a00'
  on-tertiary-fixed-variant: '#5b4300'
  background: '#faf8ff'
  on-background: '#151b2a'
  surface-variant: '#dde2f7'
typography:
  headline-xl:
    fontFamily: Plus Jakarta Sans
    fontSize: 34px
    fontWeight: '800'
    lineHeight: 40px
    letterSpacing: -0.03em
  headline-xl-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 28px
    fontWeight: '800'
    lineHeight: 34px
    letterSpacing: -0.025em
  headline-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 24px
    fontWeight: '700'
    lineHeight: 30px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 20px
    fontWeight: '700'
    lineHeight: 26px
    letterSpacing: -0.015em
  headline-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 18px
    fontWeight: '700'
    lineHeight: 24px
  body-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 17px
    fontWeight: '500'
    lineHeight: 24px
  body-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 15px
    fontWeight: '500'
    lineHeight: 22px
  body-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
  label-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 15px
    fontWeight: '700'
    lineHeight: 20px
    letterSpacing: 0.01em
  label-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 13px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.02em
  label-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 11px
    fontWeight: '800'
    lineHeight: 14px
    letterSpacing: 0.04em
  display-stat:
    fontFamily: Plus Jakarta Sans
    fontSize: 44px
    fontWeight: '800'
    lineHeight: 48px
    letterSpacing: -0.04em
rounded:
  sm: 0.5rem
  DEFAULT: 1rem
  md: 1.5rem
  lg: 2rem
  xl: 3rem
  full: 9999px
spacing:
  gutter: 0.75rem
  gutter-compact: 0.5rem
  margin: 1.25rem
  margin-mobile: 1.25rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-lg: 1rem
  space-xl: 1.5rem
  space-2xl: 2rem
---

## Brand & Style

This design system expresses a vibrant, fast-paced, and modern game-show identity tailored for mobile-first live trivia battles. Its personality is optimistic, electric, and welcoming, engineered to stimulate quick decision-making while keeping cognitive fatigue low.

The aesthetic blends clean modern app layout clarity with elevated arcade cheer:
- **Tone:** Kinetic, celebratory, approachable, and razor-sharp.
- **Audience:** Broad competitive players (ages 13+) seeking quick synchronous duels, live studio quizzes, and rapid ladder climbs.
- **Visual Style:** Modern Tactile & Crisp Flatness. The interface avoids dense skeuomorphic clutter in favor of soft, pill-rounded geometric primitives, high-legibility typographic contrasts, and micro-elevation powered by tinted warm outlines.

## Colors

The palette balances a warm cream canvas with energetic accents designed for immediate affordance and status feedback.

### Core Canvas & Neutral
- **Canvas Base:** `#FFFDF8` (Warm-white foundation eliminating harsh digital glare).
- **Ink Primary:** `#1B2130` (Deep midnight slate for crisp readability without pure black severity).
- **Ink Subtle / Secondary:** `#636D7E` (De-emphasized metadata, timers, and supporting cues).
- **Border / Divider:** `#E9E5DE` (Warm hairline divider maintaining structure softly).

### Brand & Interactive Colors
- **Primary Action (Electric Turquoise):** `#16B8A6` (Direct interactive trigger, primary buttons, active states).
- **Secondary (Competitive Pink):** `#F65F8E` (Head-to-head match indicators, streak amplifiers, high-tension triggers).
- **Tertiary (Sunny Yellow):** `#FFC94A` (Coin rewards, score multipliers, countdown warnings).

### Semantic & Tinted Surfaces
- **Success:** `#32B978` paired with **Soft Mint:** `#E8F8F5` for correct answers and tier advancement.
- **Error:** `#E95F64` paired with **Soft Rose:** `#FFF0F5` for incorrect options, timeout states, and hazards.
- **Accent Surface:** **Soft Sun:** `#FFF7D9` for prize chests and jackpot highlight containers.

## Typography

Typography prioritizes rapid-scan parsing in time-sensitive trivia matches. Plus Jakarta Sans offers open counters and geometric humanism, ensuring absolute legibility down to dense leaderboard lists.

- **Numerics & Scoreboards:** Display stats use tabular figure alignment (`font-variant-numeric: tabular-nums`) to prevent layout jump during countdowns and real-time score rolls.
- **Questions & Prompts:** Headline styles remain tight and punchy with slightly compressed line heights to fit within the viewport without pushing answer blocks off-screen.
- **Labels & Micro-cues:** Small badges and timer chips utilize bold, tracked weights for fast recognition in peripheral vision.

## Layout & Spacing

The layout model is optimized strictly around a compact mobile viewport of 390×844 (standard portrait resolution), scaling fluidly across wider devices.

- **Horizontal Margins:** Fixed `20px` (`1.25rem`) padding on left and right borders of the screen.
- **Grid Structure:** 4-column flexible grid for mobile, shifting to 6 columns on tablet screens. Gutters default to `12px` (`0.75rem`) to ensure maximum touch target area for answer panels.
- **Vertical Flow:** Trivia battle screens enforce sticky top stats (timer, round, score progress) and lock the four primary answer choices directly within the thumb reach zone at the bottom third of the display.
- **Onboarding & Flows:** Single-column layout with progressive disclosure; bottom navigation bars are strictly absent during onboarding, queue matchmaking, and live question rounds.

## Elevation & Depth

Visual hierarchy rejects heavy, murky shadows in favor of ambient warmth and delicate structural bounding.

- **Base Layer (Level 0):** Background canvas `#FFFDF8`.
- **Card & Answer Surfaces (Level 1):** Solid white `#FFFFFF` surface bounded by a crisp `1px` border of `#E9E5DE`. A whisper shadow (`0 2px 6px rgba(27, 33, 48, 0.04)`) prevents visual flattening without muddying the interface.
- **Active / Pressed (Level 0-Pressed):** Answer cards shift down `2px` with shadow collapsed to zero and border shifting to the respective primary or semantic token.
- **Floating HUD & Popups (Level 2):** Modals, live score sheets, and pinned timer panels use an elevated warm drop shadow (`0 8px 24px rgba(27, 33, 48, 0.08)`) with `1px` border `#E9E5DE`.
- **Celebration / Multiplier Overlays (Level 3):** Full-screen translucent veil (`rgba(27, 33, 48, 0.4)`) with backdrop filter blur (`8px`), elevating active match rewards.

## Shapes

The interface embraces high-roundedness primitives to communicate approachability and kinetic entertainment value.

- **Pills & Chips (`rounded-full`):** Used for countdown badges, score counters, category tags, and system controls.
- **Containers & Trivia Question Cards (`rounded-lg` / `20px` to `24px`):** Soft perimeter geometry that houses text without cutting off reading angles.
- **Answer Selection Tiles (`16px` to `20px`):** Balanced curvature that fits neatly into thumb-reach ergonomics.

## Components

### Buttons
- **Primary Action Button:** Fully rounded pill height (48–54px), solid `#16B8A6` fill, `#FFFFFF` text in `label-lg`. Pressed state transforms subtly downward with a saturated shadow ring.
- **Secondary / Duel Button:** Solid `#F65F8E` fill with white text for head-to-head actions, challenge accepts, and instant rematches.
- **Ghost / Outline Button:** Transparent background, `1.5px` border in `#E9E5DE`, ink `#1B2130`.

### Trivia Answer Cards
- **Idle State:** Background `#FFFFFF`, border `1px solid #E9E5DE`, height min `60px`, rounded `18px`, display `flex`, text aligned left with indicator pills (A, B, C, D) on the leading edge.
- **Selected State:** Border `2px solid #16B8A6`, subtle `#E8F8F5` background tint.
- **Correct State:** Instant color transition to fill `#E8F8F5`, border `2px solid #32B978`, label `#1B2130`, with a checkmark badge on the trailing edge.
- **Incorrect State:** Transition to fill `#FFF0F5`, border `2px solid #E95F64`, accompanied by a subtle horizontal micro-shake.

### Chips & Stat Badges
- Pill-shaped heights (28px and 34px), padded `12px` horizontally.
- Live Streak: Filled with `#FFF7D9`, text `#1B2130`, accented by `#FFC94A` icons.
- Category Chips: Solid white with `1px` border `#E9E5DE` and label `#636D7E`.

### Cards & Leaderboards
- **Card Surface:** Background `#FFFFFF`, rounded `20px`, padding `16px` or `20px`, outline `1px solid #E9E5DE`.
- **Matchup Split Card:** Two-sided card comparing player vs. opponent with avatar circles overlapping the central vs badge (`#F65F8E`).

### Input Fields
- Single-line inputs (room codes, handles) have a height of `52px`, rounded `16px`, background `#FFFFFF`, border `1.5px solid #E9E5DE`. Focus switches border directly to `#16B8A6` with zero fuzzy glow.

### Live Timer Ring / Bar
- Pill-shaped progress tracks (height 8px) with background `#E9E5DE`. Filled track runs `#16B8A6`, switching to `#FFC94A` under 5 seconds, and `#E95F64` under 2 seconds.