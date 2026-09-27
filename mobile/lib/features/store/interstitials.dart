import 'dart:async';
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_mobile_ads/google_mobile_ads.dart';

import '../../core/providers.dart';
import 'store_services.dart';

/// Interstitial policy (spec §31.1–31.2, §24 recovery):
/// - only after a match result is visible, never during a question or reconnect recovery;
/// - at most one opportunity per completed match and >= `interstitial_min_interval_s` between displays;
/// - a completed rewarded video satisfies that match's opportunity;
/// - not right after a crash/reconnect recovery in that match;
/// - skipped entirely with the Remove Ads entitlement;
/// - never blocks navigation: if no ad is ready, the player moves on immediately.
abstract interface class InterstitialAdGateway {
  /// Loads the next ad in the background (called during gameplay so it is ready at the result).
  void preload();

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

/// Per-session interstitial bookkeeping (business logic only; never touches match authority).
class InterstitialController {
  InterstitialController(this._ref);

  final Ref _ref;
  int? _lastShownMs;
  final _usedMatches = <String>{};
  final _recoveredMatches = <String>{};

  bool get _adFree => _ref.read(sessionProvider).value?.removeAds ?? false;

  int get _minIntervalMs {
    final s = (_ref.read(clientConfigProvider).value?['interstitial_min_interval_s'] as num?)?.toInt() ?? 45;
    return s * 1000;
  }

  /// Warm up during gameplay so an ad can be ready when the result is shown (only once consent allows ads).
  void preload() {
    if (_adFree || _ref.read(adConsentProvider).value != true) return;
    _ref.read(interstitialAdGatewayProvider).preload();
  }

  /// The match went through reconnect recovery: no interstitial right after it.
  void markRecovered(String matchId) => _recoveredMatches.add(matchId);

  /// A completed rewarded video satisfies this match's interstitial opportunity.
  void markRewarded(String matchId) => _usedMatches.add(matchId);

  bool eligible(String matchId, int nowMs) =>
      !_adFree &&
      _ref.read(adConsentProvider).value == true &&
      !_usedMatches.contains(matchId) &&
      !_recoveredMatches.contains(matchId) &&
      (_lastShownMs == null || nowMs - _lastShownMs! >= _minIntervalMs);

  /// Uses this match's opportunity when eligible; returns once the ad closed (or immediately when none).
  Future<void> maybeShow(String matchId) async {
    final now = DateTime.now().millisecondsSinceEpoch;
    if (!eligible(matchId, now)) return;
    _usedMatches.add(matchId);
    if (await _ref.read(interstitialAdGatewayProvider).showIfReady()) {
      _lastShownMs = DateTime.now().millisecondsSinceEpoch;
    }
  }
}

final interstitialControllerProvider = Provider<InterstitialController>((ref) => InterstitialController(ref));
