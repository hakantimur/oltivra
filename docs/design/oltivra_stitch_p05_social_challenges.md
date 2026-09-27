# Oltivra — Stitch Package 05: Social, Friends and Challenges

## Use

Use only after Package 04 is approved. This package designs controlled social interaction; it does not introduce chat or community content.

---

## START OF STITCH PROMPT

Apply the approved **Oltivra Design Foundation** and preserve all already approved visual components.

Generate **exactly six high-fidelity portrait mobile screens** for **Package 05 — Social, Friends and Challenges**. Use English UI copy. Outside match contexts, display the approved bottom navigation with **Social** active where applicable.

Oltivra social interaction is deliberately limited to usernames, curated avatars, friends, friend requests, friend challenges, rematches, block, and report. There is no free-text chat, voice, user profile bio, public feed, follower count, location, email, age, image upload, event wall, guild, clan, or user-created content.

### Screen 1 — Social hub: friends

- Bottom navigation with **Social** active.
- Header: **“Social”**.
- A clear search entry: **Find players by username**.
- Show a compact **Requests** summary only when relevant.
- Main content is a clean friends list: curated avatar, username, league summary, and one direct action such as **Challenge**.
- Include a warm, minimal empty-state treatment for a player with no friends; do not add suggested strangers, contacts import, follower system, or social feed.

### Screen 2 — Find players

- Bottom navigation remains visible with **Social** active.
- Heading: **“Find players”**.
- One username search input with realistic results based on exact/prefix username search.
- Each result shows only curated avatar, username, small league summary, and relationship state.
- Provide a concise **Add friend** action when appropriate.
- Do not show real name, profile bio, country, distance, online location, mutual-contact graph, or multi-field people search.

### Screen 3 — Public player profile

- Bottom navigation remains visible with **Social** active.
- Show only: curated avatar, username, league summary, selected cosmetic frame/badge, and concise public competitive highlights.
- Show the correct relationship action state, such as **Add friend**, **Request sent**, or **Challenge** for an accepted friend.
- Include a discreet overflow control for **Block** and **Report**; do not render those confirmation flows in this package.
- Do not show private data, post history, chat, followers, location, a bio, social media links, or profile editing for another player.

### Screen 4 — Friend requests

- Bottom navigation remains visible with **Social** active.
- Heading: **“Friend requests”**.
- Show incoming requests as concise cards with avatar and username only.
- Each request has exactly two clear actions: **Accept** and **Decline**.
- Show an unobtrusive outgoing-pending section if space permits; no message field or request note.
- Do not add friend recommendations, invitations through contacts, or activity feed content.

### Screen 5 — Create a friend challenge

- No bottom navigation; this is a focused Quick Battle party lobby.
- Heading: **“Challenge friends”**.
- State clearly: **“Quick Battle · 2–4 friends · missing places are filled at start.”**
- Show a party roster with host plus up to three invited friend slots. Use accepted-friend names and curated avatars only.
- Include a simple language disclosure: **“Question language: English”**.
- Primary action: **Invite friends**. Once at least two accepted friends are present, allow a secondary start state: **Start battle**.
- Keep a small 60-second invitation expiry treatment, but do not show invite codes, public rooms, spectator invites, chat, custom rules, category selection, or bot labels.

### Screen 6 — Incoming friend challenge

- No bottom navigation.
- Show inviter avatar/username, then: **“invited you to a Quick Battle.”**
- State the question language clearly: **“English questions”**.
- Primary action: **Accept challenge**.
- Secondary action: **Decline**.
- Include a compact expiry indicator. Do not provide a message response, counter-offer, custom mode, category setting, or payment/entry mechanism.

### Package guardrails

- Use the same compact avatar and league-chip treatment everywhere.
- Social controls must be secondary to the live game; avoid turning this area into a community platform.
- The 10-second Rematch control belongs on match result screens already designed; do not create a separate rematch hub.
- End after these six screens. Do not design rankings, missions, profile management, settings, or monetisation screens yet.

## END OF STITCH PROMPT
