import 'dart:async';

import 'package:firebase_analytics/firebase_analytics.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Product events for Google Ads app campaigns (optimise on players who actually play, not just installs).
/// Fire-and-forget: analytics never affects play.
abstract class Analytics {
  void matchCompleted({required String mode});
  void levelUp({required int level});
}

/// Local builds, emulators and tests.
class NoopAnalytics implements Analytics {
  const NoopAnalytics();

  @override
  void matchCompleted({required String mode}) {}

  @override
  void levelUp({required int level}) {}
}

class FirebaseAnalyticsService implements Analytics {
  FirebaseAnalyticsService([FirebaseAnalytics? analytics]) : _fa = analytics ?? FirebaseAnalytics.instance;

  final FirebaseAnalytics _fa;

  @override
  void matchCompleted({required String mode}) =>
      _send(() => _fa.logEvent(name: 'match_completed', parameters: {'mode': mode}));

  @override
  void levelUp({required int level}) => _send(() => _fa.logLevelUp(level: level));

  void _send(Future<void> Function() log) {
    unawaited(() async {
      try {
        await log();
      } catch (_) {
        // Analytics never affects play.
      }
    }());
  }
}

/// Overridden in `main()` with [FirebaseAnalyticsService] on real (non-emulator) Firebase builds.
final analyticsProvider = Provider<Analytics>((ref) => const NoopAnalytics());
