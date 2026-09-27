import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_database/firebase_database.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../core/env.dart';
import '../core/providers.dart';
import 'match_snapshot.dart';

/// Connection health shown by the reconnect banner (design P08 "Reconnecting to battle").
enum LiveHealth { connected, reconnecting, unavailable }

class LiveUpdate {
  const LiveUpdate(this.snapshot, this.health);

  final MatchSnapshot? snapshot;
  final LiveHealth health;
}

/// Streams the viewer's safe projection of a match.
///
/// Both implementations also drive `POST /v1/matches/{id}/sync` when a server deadline has passed without a
/// state change (spec §20.5): the server resolves idempotently, so a late or duplicate sync is harmless.
abstract class MatchLiveSource {
  Stream<LiveUpdate> watch(String matchId);
}

/// Polls `GET /v1/matches/{id}` (the reconnect snapshot). Used for local development without Firebase and as
/// the fallback when a Realtime Database listener cannot connect.
class PollingLiveSource implements MatchLiveSource {
  PollingLiveSource(this._api, this._clock);

  final ApiClient _api;
  final ServerClock _clock;

  @override
  Stream<LiveUpdate> watch(String matchId) {
    late StreamController<LiveUpdate> controller;
    var cancelled = false;
    var failures = 0;
    var lastSyncVersion = -1;

    Future<void> loop() async {
      MatchSnapshot? last;
      while (!cancelled) {
        try {
          final snapshot = MatchSnapshot.fromView(await _api.get('/v1/matches/$matchId'));
          if (snapshot.receivedAtMs > 0) _clock.observe(snapshot.receivedAtMs);
          failures = 0;
          last = snapshot;
          if (!cancelled) controller.add(LiveUpdate(snapshot, LiveHealth.connected));
          final due = snapshot.nextServerEventAtMs;
          if (!snapshot.isTerminal && due > 0 && _clock.nowMs() > due + 350 &&
              lastSyncVersion != snapshot.stateVersion) {
            lastSyncVersion = snapshot.stateVersion;
            unawaited(_api
                .post('/v1/matches/$matchId/sync', {'observed_state_version': snapshot.stateVersion})
                .catchError((_) => <String, dynamic>{}));
          }
          if (snapshot.isTerminal && snapshot.settlementStatus == 'SETTLED') {
            await Future<void>.delayed(const Duration(seconds: 3));
            continue;
          }
          await Future<void>.delayed(
              snapshot.isQuestionLive ? const Duration(milliseconds: 450) : const Duration(milliseconds: 700));
        } on ApiException catch (e) {
          if (e.code == 'MATCH_NOT_FOUND' || e.code == 'NOT_MATCH_PARTICIPANT' || e.code == 'NOT_FOUND') {
            if (!cancelled) controller.add(LiveUpdate(last, LiveHealth.unavailable));
            return;
          }
          failures++;
          if (!cancelled) {
            controller.add(LiveUpdate(last, failures > 20 ? LiveHealth.unavailable : LiveHealth.reconnecting));
          }
          await Future<void>.delayed(Duration(milliseconds: 400 * failures.clamp(1, 8)));
        }
      }
    }

    controller = StreamController<LiveUpdate>(
      onListen: loop,
      onCancel: () => cancelled = true,
    );
    return controller.stream;
  }
}

/// Realtime Database listeners on `matches/{id}/public` and `matches/{id}/player_private/{uid}` of the match's
/// shard (spec §14.1, §17). The first snapshot comes from the API so the shard URL is known.
class RtdbLiveSource implements MatchLiveSource {
  RtdbLiveSource(this._api, this._clock, this._uid);

  final ApiClient _api;
  final ServerClock _clock;
  final String? Function() _uid;

  @override
  Stream<LiveUpdate> watch(String matchId) async* {
    final first = MatchSnapshot.fromView(await _api.get('/v1/matches/$matchId'));
    yield LiveUpdate(first, LiveHealth.connected);
    final url = first.rtdbUrl;
    if (url == null) {
      yield* PollingLiveSource(_api, _clock).watch(matchId);
      return;
    }
    final db = FirebaseDatabase.instanceFor(app: Firebase.app(), databaseURL: url);
    final uid = _uid();
    final controller = StreamController<LiveUpdate>();
    var snapshot = first;
    var connected = true;
    final subs = <StreamSubscription<DatabaseEvent>>[];
    Timer? deadline;

    void emit() => controller.add(LiveUpdate(snapshot, connected ? LiveHealth.connected : LiveHealth.reconnecting));

    void armSync() {
      deadline?.cancel();
      final due = snapshot.nextServerEventAtMs;
      if (due <= 0 || snapshot.isTerminal) return;
      final version = snapshot.stateVersion;
      deadline = Timer(Duration(milliseconds: (due - _clock.nowMs() + 350).clamp(0, 60000)), () {
        if (snapshot.stateVersion == version) {
          _api.post('/v1/matches/$matchId/sync', {'observed_state_version': version}).catchError((_) => <String, dynamic>{});
        }
      });
    }

    subs.add(db.ref('matches/$matchId/public').onValue.listen((event) {
      final value = event.snapshot.value;
      if (value is Map) {
        snapshot = snapshot.copyWith(public: _deepCast(value));
        emit();
        armSync();
      }
    }, onError: (_) {
      connected = false;
      emit();
    }));
    if (uid != null && !first.isSpectator) {
      subs.add(db.ref('matches/$matchId/player_private/$uid').onValue.listen((event) {
        final value = event.snapshot.value;
        if (value is Map) {
          snapshot = snapshot.copyWith(private: _deepCast(value));
          emit();
        }
      }));
    }
    subs.add(db.ref('.info/connected').onValue.listen((event) {
      connected = event.snapshot.value == true;
      emit();
    }));
    controller.onCancel = () {
      deadline?.cancel();
      for (final s in subs) {
        s.cancel();
      }
    };
    yield* controller.stream;
  }

  static Map<String, dynamic> _deepCast(Map value) => value.map((k, v) => MapEntry(k.toString(), _cast(v)));

  static dynamic _cast(dynamic v) => switch (v) {
        Map m => _deepCast(m),
        List l => l.map(_cast).toList(),
        _ => v,
      };
}

final matchLiveSourceProvider = Provider<MatchLiveSource>((ref) {
  final api = ref.watch(apiClientProvider);
  final clock = ref.watch(serverClockProvider);
  if (Env.pollLive) return PollingLiveSource(api, clock);
  final auth = ref.watch(authServiceProvider);
  return RtdbLiveSource(api, clock, () => auth.current?.uid);
});

/// Live projection of one match; screens `ref.watch(matchLiveProvider(id))`.
final matchLiveProvider = StreamProvider.autoDispose.family<LiveUpdate, String>(
  (ref, matchId) => ref.watch(matchLiveSourceProvider).watch(matchId),
);
