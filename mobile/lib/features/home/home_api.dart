import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_client.dart';
import '../../core/providers.dart';

/// `GET /v1/missions/daily` → `{period_id, ends_at_ms, missions: [{mission_id, template_id, target, progress, ...}]}`.
final homeDailyMissionsProvider = FutureProvider.autoDispose<Json>((ref) async {
  await ref.watch(authStateProvider.future);
  return ref.read(apiClientProvider).get('/v1/missions/daily');
});

/// `GET /v1/league` → league + abstract progress + `ranked_weekly_xp` (never raw MMR).
final homeLeagueProvider = FutureProvider.autoDispose<Json>((ref) async {
  await ref.watch(authStateProvider.future);
  return ref.read(apiClientProvider).get('/v1/league');
});

/// `GET /v1/leaderboards/weekly?limit=1` — only `me` (own weekly rank) is used on Home; `null` when unranked.
final homeWeeklyRankProvider = FutureProvider.autoDispose<Json?>((ref) async {
  await ref.watch(authStateProvider.future);
  final res = await ref.read(apiClientProvider).get('/v1/leaderboards/weekly', query: {'limit': '1'});
  return (res['me'] as Map?)?.cast<String, dynamic>();
});

/// Median RTT (ms) over [samples] authenticated `GET /v1/ping` calls (spec §21.2). Used for grouping only.
/// Failed samples are skipped; throws the last error when every sample fails.
Future<int> measureMedianRtt(ApiClient api, {int samples = 5, int Function()? nowMs}) async {
  final clock = nowMs ?? () => DateTime.now().millisecondsSinceEpoch;
  final rtts = <int>[];
  Object? lastError;
  for (var i = 0; i < samples; i++) {
    final started = clock();
    try {
      await api.get('/v1/ping');
      rtts.add((clock() - started).clamp(0, 10000));
    } catch (e) {
      lastError = e;
    }
  }
  if (rtts.isEmpty) throw lastError ?? ApiException(0, 'NETWORK_UNAVAILABLE', retryable: true);
  rtts.sort();
  return rtts[rtts.length ~/ 2];
}

/// Typed view over the matchmaking join/status/leave responses (backend `_queued_view` / `_matched_view`).
class QueueStatus {
  QueueStatus(this.raw);

  final Json raw;

  String get state => (raw['state'] as String?) ?? 'IDLE';
  bool get isQueued => state == 'QUEUED';
  bool get isMatched => state == 'MATCHED';
  bool get isOver => state == 'EXPIRED' || state == 'CANCELLED' || state == 'IDLE';
  bool get isSettling => state == 'SETTLEMENT_PENDING';
  bool get capacityLimited => raw['capacity_limited'] == true;
  String? get matchId => (raw['match'] as Map?)?['match_id'] as String?;
  int? get nextPollAtMs => (raw['next_poll_at_ms'] as num?)?.toInt();
  int? get expiresAtMs => (raw['expires_at_ms'] as num?)?.toInt();
  int? get serverTimeMs => (raw['server_time_ms'] as num?)?.toInt();
}
