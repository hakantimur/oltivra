# Oltivra — Google Stitch Design Foundation Prompt

## Use

Paste the prompt below into Google Stitch as the **first and permanent design brief**. It establishes the product, visual system, and the strict package-by-package workflow. It does **not** ask Stitch to generate screens yet.

---

## START OF STITCH PROMPT

You are establishing the permanent design foundation for **Oltivra: Live Trivia Battles**.

This is a **13+ global live multiplayer trivia game**. Its feeling must be fast, social, competitive, intelligent, optimistic, and premium. It is not a children’s learning app, a classroom tool, an esports product, or a dark sci-fi game.

Brand line: **“Think fast. Rise higher.”**

### Product context

Oltivra has two live competitive modes:

- **Quick Battle:** four players, ten questions, 11-second rounds. The first accepted correct answer earns speed-based points; a wrong answer costs points.
- **Survival:** ten players, 11-second rounds. Wrong or missing answers normally eliminate a player until one winner remains.

The product also includes XP and levels, leagues, weekly ranking, win streaks, Survival crowns, missions, cosmetic badges and frames, category statistics, friends, friend challenges, rematches, block/report, and a limited curated reaction system.

Social interaction is intentionally controlled. There is **no free-text chat, voice chat, user-uploaded avatar, user-generated trivia, open community feed, virtual currency store, map, pet, collectible system, or pay-to-win mechanic**.

At launch, public matching is global and uses a mixed category pool. The nine content categories are Geography & World, Science & Nature, History, Sports, Movies & TV, Music, Food & Culture, Technology & Inventions, and Arts & Literature.

### Core design position

Create a **clean live game-show experience inside a modern premium mobile product**:

- As easy to understand as a live quiz game.
- As competitive and socially motivating as a league-based trivia game.
- More focused, less noisy, and more mature than a typical casual trivia app.

The interface must make the next action obvious. Each screen should have one clear primary decision. The player must never feel lost, buried under cards, or pushed through artificial engagement loops.

### Audience and tone

- Audience: 13+; globally understandable.
- Tone: sharp, encouraging, confident, friendly, and lightly playful.
- Never patronising, childish, overly academic, aggressive, or gambling-like.
- Use concise, natural English UI copy in all future screens unless a package specifies another language.

### Permanent visual direction

Use a bright, warm, premium light theme. The app should feel energetic without becoming loud.

#### Colour system

| Role | Colour | Use |
|---|---:|---|
| Warm canvas | `#FFFDF8` | Main screen background |
| Ink | `#1B2130` | Primary text and dark icons |
| Turquoise | `#16B8A6` | Primary action, active states, Quick Battle identity |
| Pink | `#F65F8E` | Competitive energy, streaks, selected highlights |
| Sunny yellow | `#FFC94A` | Rewards, achievement moments, timer emphasis |
| Success green | `#32B978` | Correct/success states only |
| Error coral | `#E95F64` | Wrong/error states only |
| Soft mint | `#E8F8F5` | Secondary turquoise surface |
| Soft rose | `#FFF0F5` | Secondary pink surface |
| Soft sun | `#FFF7D9` | Secondary yellow surface |
| Divider | `#E9E5DE` | Borders and quiet separators |

Use colour semantically and sparingly. Turquoise is the main action colour. Pink provides energy, yellow signals attention or reward, green confirms success, and coral signals an error. Never use brand pink as an error state.

#### Typography and components

- Use one modern, highly legible rounded sans-serif family, comparable to **Manrope** or **Plus Jakarta Sans**.
- Prioritise bold, compact headings and comfortably readable body text.
- Use generous whitespace, 20 px horizontal mobile margins, and clear touch targets.
- Cards use soft 16–20 px corner radii, a subtle 1 px warm border, and little or no shadow.
- Buttons are solid and clear; the primary action is visually dominant.
- Use restrained rounded icons; do not use dense icon grids.
- Show progress, rank, streak, and reward as compact status elements rather than large decorative widgets.
- Use simple original abstract shapes only when they support hierarchy; do not use stock photos or decorative character art unless a future package explicitly requests it.

#### Explicit visual exclusions

Do **not** use:

- Purple, violet, blue-purple, or rainbow gradients.
- Dark cyberpunk interfaces, neon glow, holograms, space/AI imagery, or esports styling.
- Heavy glassmorphism, gradient blobs, excessive shadows, or busy background patterns.
- Childish mascots, cartoon worlds, classroom chalkboards, spinning prize wheels, candy-style map progression, or excessive confetti.
- Generic SaaS dashboards, dense analytics tables, excessive cards, carousels, banners, or decorative badges.
- A permanent dark mode in the initial design work.

### Navigation and live-match principles

Outside a match, the eventual app structure will use five simple destinations:

**Home · Play · Rankings · Social · Profile**

During a live match, remove the bottom navigation and nonessential chrome. Preserve stable visual regions for the timer, player status, question/media, four answer options, score or survival state, and reactions.

On question screens, the hierarchy is always:

1. Remaining time and compact match status.
2. The question and optional approved question image.
3. Four large, immediately tappable answer choices.
4. Player score/survival information.

Curated reactions must be small, temporary, and placed away from the question, options, timer, and all tap targets.

### Accessibility and mobile standard

- Design mobile-first for a 390 × 844 portrait viewport, with clean future responsiveness.
- Maintain strong text contrast and non-colour-only state indicators.
- Make answer options and primary actions easy to tap with one hand.
- Avoid tiny text, cramped controls, low-contrast coloured text, and layout shifts.
- Reserve safe areas and avoid placing essential controls against device edges.

### Strict staged workflow — mandatory

This message is only the design foundation. **Do not create screens, an app map, a prototype, a logo, or extra features now.**

I will provide future requests as sequential packages of **five or six explicitly named screens**. For each package:

1. Generate **only** the listed screens and the explicitly requested state variants.
2. Do not add, remove, merge, rename, or infer any screens, features, menus, flows, monetisation elements, animations, or social functions.
3. Do not redesign or alter an earlier approved screen unless the package explicitly asks for that revision.
4. Reuse this exact visual system and component language across every package.
5. If a product detail is not stated in the package, use the smallest neutral visual treatment needed; do not invent product functionality.
6. After completing a package, stop. Do not begin the next package until I provide it after review.

Your role is to execute the requested screen package faithfully, not to expand the product scope.

Reply only with a short acknowledgement that you will preserve this design foundation and wait for **Package 1**.

## END OF STITCH PROMPT
