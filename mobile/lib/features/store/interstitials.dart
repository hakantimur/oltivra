import 'dart:async';
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_mobile_ads/google_mobile_ads.dart';

import '../../core/providers.dart';
import 'store_services.dart';

/// Ad break policy (playtest 2026-09-27, replaces the per-result interstitial of spec §31.1):
/// - after every `ad_gate_every_matches` completed matches (default 3), the next match starts after one
///   interstitial, announced first by a short notice card explaining why Oltivra shows ads;
/// - never during a match: the break runs on the matchmaking screen before joining the queue;
/// - skipped entirely with the Remove Ads entitlement or without ad consent;
/// - never blocks play: no fill, offline or a failed show lets the player straight into matchmaking, and the
///   break is offered again before a later match.
abstract interface class InterstitialAdGateway {
  /// Loads the next ad in the background (called during gameplay so it is ready at the next break).
  void preload();

  /// Whether an ad is loaded and can be shown right now.
  bool get isReady;

  /// Shows a loaded ad and completes when it is dismissed; `false` when none was ready.
  Future<bool> showIfReady();
}

/// AdMob unit ids come from `--dart-define` so release builds use real units; Google's public sample units
/// are the development default.
const interstitialAdUnitAndroid = String.fromEnvironment(
  'ADMOB_INTERSTITIAL_ANDROID',
  defaultValue: 'ca-app-pub-3940256099942544/1033173712',
);
const interstitialAdUnitIos = String.fromEnvironment(
  'ADMOB_INTERSTITIAL_IOS',
  defaultValue: 'ca-app-pub-3940256099942544/4411468910',
);

class GoogleInterstitialAdGateway implements InterstitialAdGateway {
  GoogleInterstitialAdGateway({required this.personalized});

  final bool Function() personalized;
  InterstitialAd? _ad;
  bool _loading = false;

  String get _unit => !kIsWeb && Platform.isIOS ? interstitialAdUnitIos : interstitialAdUnitAndroid;

  @override
  bool get isReady => _ad != null;

  @override
  void preload() {
    if (_ad != null || _loading) return;
    _loading = true;
    unawaited(() async {
      try {
        await MobileAds.instance.initialize();
        await InterstitialAd.load(
          adUnitId: _unit,
          request: AdRequest(nonPersonalizedAds: !personalized()),
          adLoadCallback: InterstitialAdLoadCallback(
            onAdLoaded: (ad) {
              _ad = ad;
              _loading = false;
            },
            onAdFailedToLoad: (_) => _loading = false,
          ),
        );
      } catch (_) {
        _loading = false;
      }
    }());
  }

  @override
  Future<bool> showIfReady() async {
    final ad = _ad;
    if (ad == null) {
      preload();
      return false;
    }
    _ad = null;
    final done = Completer<bool>();
    ad.fullScreenContentCallback = FullScreenContentCallback(
      onAdDismissedFullScreenContent: (ad) {
        ad.dispose();
        if (!done.isCompleted) done.complete(true);
      },
      onAdFailedToShowFullScreenContent: (ad, _) {
        ad.dispose();
        if (!done.isCompleted) done.complete(false);
      },
    );
    await ad.show();
    final shown = await done.future;
    preload();
    return shown;
  }
}

final interstitialAdGatewayProvider = Provider<InterstitialAdGateway>(
  (ref) => GoogleInterstitialAdGateway(
    personalized: () => ref.read(sharedPrefsProvider).getBool(personalizedAdsPrefKey) ?? true,
  ),
);

/// Completed matches since the last ad break, persisted so the rhythm survives app restarts.
const adGateCountPrefKey = 'ads.matches_since_break';
const adGateLastMatchPrefKey = 'ads.last_counted_match';

/// Ad break bookkeeping (business logic only; never touches match authority).
class InterstitialController {
  InterstitialController(this._ref);

  final Ref _ref;

  bool get _adFree => _ref.read(sessionProvider).value?.removeAds ?? false;

  bool get _adsAllowed => !_adFree && _ref.read(adConsentProvider).value == true;

  int get every => (_ref.read(clientConfigProvider).value?['ad_gate_every_matches'] as num?)?.toInt() ?? 3;

  int get completedSinceBreak => _ref.read(sharedPrefsProvider).getInt(adGateCountPrefKey) ?? 0;

  /// Warm up during gameplay so an ad can be ready for the next break (only once consent allows ads).
  void preload() {
    if (!_adsAllowed) return;
    _ref.read(interstitialAdGatewayProvider).preload();
  }

  /// Counts a completed match once (idempotent per match id).
  Future<void> recordCompleted(String matchId) async {
    final prefs = _ref.read(sharedPrefsProvider);
    if (prefs.getString(adGateLastMatchPrefKey) == matchId) return;
    await prefs.setString(adGateLastMatchPrefKey, matchId);
    await prefs.setInt(adGateCountPrefKey, completedSinceBreak + 1);
  }

  /// Whether the next match should start with an ad break. An ad that is not loaded yet never blocks play;
  /// it is requested for a later break instead.
  bool breakDue() {
    if (every <= 0 || completedSinceBreak < every || !_adsAllowed) return false;
    final gateway = _ref.read(interstitialAdGatewayProvider);
    if (gateway.isReady) return true;
    gateway.preload();
    return false;
  }

  /// Shows [notice] (the pre-ad card), then the interstitial. The counter resets only once an ad was shown.
  Future<void> runBreak(Future<void> Function() notice) async {
    await notice();
    if (await _ref.read(interstitialAdGatewayProvider).showIfReady()) {
      await _ref.read(sharedPrefsProvider).setInt(adGateCountPrefKey, 0);
    }
  }
}

final interstitialControllerProvider = Provider<InterstitialController>((ref) => InterstitialController(ref));
