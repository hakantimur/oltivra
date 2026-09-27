import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_client.dart';
import '../../core/providers.dart';

/// Read models for the progress package (spec §27.6). All values are server projections; the client never
/// derives ranks, league progress or rewards. Raw MMR is never part of any response.

/// `GET /v1/leaderboards/weekly` — global (`league == null`) or filtered to one league.
final weeklyLeaderboardProvider = FutureProvider.autoDispose.family<Json, String?>((ref, league) {
  return ref.read(apiClientProvider).get('/v1/leaderboards/weekly', query: {
    'limit': '50',
    'league': ?league,
  });
});

/// `GET /v1/league` — league + abstract 0..1 progress, placement state and ladder.
final leagueStatusProvider = FutureProvider.autoDispose<Json>((ref) => ref.read(apiClientProvider).get('/v1/league'));

/// `GET /v1/missions/daily|weekly`; [period] is `daily` or `weekly`.
final missionsProvider = FutureProvider.autoDispose.family<Json, String>(
  (ref, period) => ref.read(apiClientProvider).get('/v1/missions/$period'),
);

/// `GET /v1/category-stats`.
final categoryStatsProvider =
    FutureProvider.autoDispose<Json>((ref) => ref.read(apiClientProvider).get('/v1/category-stats'));

/// `GET /v1/match-history` (own recent matches, most recent first).
final matchHistoryProvider = FutureProvider.autoDispose<Json>(
  (ref) => ref.read(apiClientProvider).get('/v1/match-history', query: {'limit': '10'}),
);

/// Re-reads the own profile after a server-side change (mission claim, cosmetics) and applies it to the session.
Future<void> reloadOwnProfile(WidgetRef ref) async {
  final res = await ref.read(apiClientProvider).get('/v1/profile');
  final profile = res['profile'];
  if (profile is Map) ref.read(sessionProvider.notifier).applyProfile(profile.cast<String, dynamic>());
}

// ------------------------------------------------------------------------------------------ small parsers

Json asJson(Object? v) => v is Map ? v.cast<String, dynamic>() : const {};

List<Json> asJsonList(Object? v) => v is List ? [for (final e in v) if (e is Map) e.cast<String, dynamic>()] : const [];

int? asInt(Object? v) => v is num ? v.toInt() : null;

double? asDouble(Object? v) => v is num ? v.toDouble() : null;

/// Next ISO week start (Monday 00:00 UTC) after [nowMs] — the weekly leaderboard period boundary (display only).
int nextIsoWeekStartMs(int nowMs) {
  const day = 86400000;
  final dt = DateTime.fromMillisecondsSinceEpoch(nowMs, isUtc: true);
  final midnight = (nowMs ~/ day) * day;
  return midnight + (8 - dt.weekday) * day; // DateTime.weekday: Monday = 1
}
