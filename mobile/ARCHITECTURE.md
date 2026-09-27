# Oltivra mobile (Flutter) — architecture

Authoritative server, thin client. The app renders server projections and sends intents; it never decides
scores, correctness, rankings or rewards (spec §0.1, §17).

## Running locally

```
docker compose up          # Firebase emulators + API on :8000 (or: cd backend && uvicorn app.main:app_from_env --factory --port 8000)
cd mobile && flutter run   # Android emulator; host reachable at 10.0.2.2
```

`--dart-define` flags (see `lib/core/env.dart`):

| flag | default | meaning |
|---|---|---|
| `API_BASE_URL` | `http://10.0.2.2:8000` | backend origin |
| `AUTH_MODE` | `fake` | `fake`: `test:<uid>` tokens accepted by the dev backend; `firebase`: Firebase Auth (emulator) |
| `LIVE_MODE` | `poll` | `poll`: `GET /v1/matches/{id}`; `rtdb`: Realtime Database listeners on the match shard |
| `USE_EMULATORS` | `true` | point Firebase SDKs at the local emulators |

## Layout

```
lib/
  api/api_client.dart        HTTP client: bearer + App Check headers, UUIDv4 request_id + x-idempotency-key on
                             every mutation, error envelope -> ApiException(code, detail, retryable)
  auth/auth_service.dart     AuthService (Fake / Firebase): Google, Apple, email
  core/env.dart              build-time config
  core/providers.dart        Riverpod: sharedPrefs, auth, apiClient, locale, localOnboarding, session,
                             serverClock, clientConfig, catalogProvider('avatars'|'reactions'|'cosmetics'|'categories')
  session/session.dart       typed bootstrap (onboarding flags, profile, runtime pointer, features)
  live/match_snapshot.dart   typed public + player_private projection of a match
  live/match_live_source.dart  PollingLiveSource / RtdbLiveSource, matchLiveProvider(matchId)
  l10n/strings.dart          context.t('key', {'arg': v}); context.pick({'en':..,'tr':..})
  l10n/tables/<pkg>.dart     per-package string tables (en + tr, same keys)
  router/routes.dart         every route path; router/app_router.dart wires screens + onboarding redirect
  theme/                     tokens (OColors, OSpace, ORadius, OShadow, ODuration) + OText + buildTheme()
  widgets/o_widgets.dart     OButton, OCircleButton, OCard, OSectionHeader, OPill, OProgressBar, OPage,
                             OLoading, OEmptyState, OErrorView, errorText/showError/showMessage,
                             shortDuration, categoryIcon, leagueColor
  widgets/o_avatar.dart      OAvatar(avatarId, size, frameId) — vector motifs from the curated catalog
  features/<pkg>/            screens + package-local widgets/api helpers
```

## Rules

- **No bot labels anywhere** (decision D3): players are rendered identically; `is_bot`/`kind` never exist client side.
- Never invent numbers (online counts, ranks, streaks). Show only what the API returns; hide a widget when data is absent.
- All user-visible text goes through `context.t`, with both `en` and `tr` entries.
- Mutations use `ref.read(apiClientProvider).post/patch/put/delete(path, body)`; the client adds the idempotency key.
  After a mutation that returns `{"profile": {...}}`, call `ref.read(sessionProvider.notifier).applyProfile(profile)`.
- Errors: `showError(context, e)` for actions, `OErrorView(error:, onRetry:)` for failed loads.
- Countdowns use `ref.read(serverClockProvider).nowMs()` against server `*_at_ms` deadlines; they are display only.
- Tap targets >= 48px, text scales, semantic labels on icon-only buttons.
