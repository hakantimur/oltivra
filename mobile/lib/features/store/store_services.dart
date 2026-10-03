import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_mobile_ads/google_mobile_ads.dart';
import 'package:in_app_purchase/in_app_purchase.dart';

import '../../core/providers.dart';
import 'ad_diagnostics.dart';

/// Thin wrappers over the ad (google_mobile_ads) and purchase (in_app_purchase) plugins so screens stay
/// testable: tests override the providers below and never touch platform channels.

/// Non-consumable product id (backend `app/purchases/service.py` PRODUCT_ID).
const removeAdsProductId = 'remove_ads_forever';

/// Google's public sample rewarded units — safe for development; replace per platform before release.
/// Real AdMob units are passed with `--dart-define`; Google's public sample units are the development default.
const rewardedAdUnitAndroid = String.fromEnvironment(
  'ADMOB_REWARDED_ANDROID',
  defaultValue: 'ca-app-pub-3940256099942544/5224354917',
);
const rewardedAdUnitIos = String.fromEnvironment(
  'ADMOB_REWARDED_IOS',
  defaultValue: 'ca-app-pub-3940256099942544/1712485313',
);

/// Local preference used when no UMP privacy-options form applies (outside EEA/UK/CH): `false` requests
/// non-personalised ads.
const personalizedAdsPrefKey = 'ads.personalized';

/// Dev backend shared secret (`Settings.internal_shared_secret` default). Used only when `Env.fakeAuth`
/// to reproduce the backend's fake SSV / fake App Store verifiers against the local API.
const devInternalSecret = String.fromEnvironment('DEV_INTERNAL_SECRET', defaultValue: 'dev-internal-secret');

/// Bundle id the backend fake Apple verifier expects (`Settings.apple_bundle_id`).
const devAppleBundleId = String.fromEnvironment('APPLE_BUNDLE_ID', defaultValue: 'com.oltivra.app');

// ------------------------------------------------------------------------------------------ rewarded ads

enum RewardedAdOutcome { earned, dismissed, failed }

abstract interface class RewardedAdGateway {
  /// Loads and shows one rewarded ad bound to the server offer via SSV `userId` + `customData`.
  Future<RewardedAdOutcome> show({required String userId, required String customData});
}

class GoogleRewardedAdGateway implements RewardedAdGateway {
  GoogleRewardedAdGateway({required this.personalized, this.onLoad});

  /// Reports each load result (stage `load_rewarded`) to [AdDiagnostics].
  final void Function(bool ok, {Object? code, String detail})? onLoad;

  final bool Function() personalized;
  static Future<InitializationStatus>? _init;

  String get _unit => !kIsWeb && Platform.isIOS ? rewardedAdUnitIos : rewardedAdUnitAndroid;

  @override
  Future<RewardedAdOutcome> show({required String userId, required String customData}) async {
    try {
      await (_init ??= MobileAds.instance.initialize());
      final loaded = Completer<RewardedAd>();
      await RewardedAd.load(
        adUnitId: _unit,
        request: AdRequest(nonPersonalizedAds: !personalized()),
        rewardedAdLoadCallback: RewardedAdLoadCallback(
          onAdLoaded: (ad) {
            onLoad?.call(true);
            loaded.complete(ad);
          },
          onAdFailedToLoad: (error) {
            onLoad?.call(false, code: error.code, detail: error.message);
            loaded.completeError(error);
          },
        ),
      );
      final ad = await loaded.future.timeout(const Duration(seconds: 20));
      await ad.setServerSideOptions(ServerSideVerificationOptions(userId: userId, customData: customData));
      final done = Completer<RewardedAdOutcome>();
      var earned = false;
      ad.fullScreenContentCallback = FullScreenContentCallback(
        onAdDismissedFullScreenContent: (ad) {
          ad.dispose();
          if (!done.isCompleted) done.complete(earned ? RewardedAdOutcome.earned : RewardedAdOutcome.dismissed);
        },
        onAdFailedToShowFullScreenContent: (ad, _) {
          ad.dispose();
          if (!done.isCompleted) done.complete(RewardedAdOutcome.failed);
        },
      );
      await ad.show(onUserEarnedReward: (_, _) => earned = true);
      return await done.future;
    } catch (_) {
      return RewardedAdOutcome.failed;
    }
  }
}

final rewardedAdGatewayProvider = Provider<RewardedAdGateway>(
  (ref) => GoogleRewardedAdGateway(
    personalized: () => ref.read(sharedPrefsProvider).getBool(personalizedAdsPrefKey) ?? true,
    onLoad: (ok, {code, detail = ''}) =>
        ref.read(adDiagnosticsProvider).report('load_rewarded', ok: ok, code: code, detail: detail),
  ),
);

// ------------------------------------------------------------------------------------------ consent (UMP)

class AdConsentState {
  const AdConsentState({required this.privacyOptionsRequired, required this.canRequestAds});

  /// The UMP privacy-options form applies (EEA/UK/CH): the platform form is the source of truth.
  final bool privacyOptionsRequired;
  final bool canRequestAds;
}

abstract interface class AdConsentGateway {
  Future<AdConsentState> refresh();

  /// Startup flow (spec §31): refresh consent info and show the UMP consent form when the region requires it.
  /// Returns whether ads may be requested.
  Future<bool> gather();

  /// Why the last consent update failed (`<code>: <message>`), or null.
  String? get lastError;

  Future<void> showPrivacyOptions();
}

class UmpConsentGateway implements AdConsentGateway {
  @override
  String? lastError;

  @override
  Future<AdConsentState> refresh() async {
    final info = ConsentInformation.instance;
    final updated = Completer<void>();
    info.requestConsentInfoUpdate(
      ConsentRequestParameters(),
      () => updated.complete(),
      (error) => updated.completeError('${error.errorCode}: ${error.message}'),
    );
    await updated.future.timeout(const Duration(seconds: 10));
    final status = await info.getPrivacyOptionsRequirementStatus();
    return AdConsentState(
      privacyOptionsRequired: status == PrivacyOptionsRequirementStatus.required,
      canRequestAds: await info.canRequestAds(),
    );
  }

  @override
  Future<bool> gather() async {
    // Google's UMP flow: a failed update (offline, timeout, publisher misconfiguration) still falls back to
    // canRequestAds(), which reflects the consent status cached from an earlier run.
    lastError = null;
    try {
      await refresh();
      final done = Completer<void>();
      ConsentForm.loadAndShowConsentFormIfRequired((error) => done.complete());
      await done.future;
    } catch (e) {
      lastError = '$e';
    }
    return ConsentInformation.instance.canRequestAds();
  }

  @override
  Future<void> showPrivacyOptions() async {
    final done = Completer<void>();
    await ConsentForm.showPrivacyOptionsForm((error) {
      if (error == null) {
        done.complete();
      } else {
        done.completeError(error.message);
      }
    });
    return done.future;
  }
}

final adConsentGatewayProvider = Provider<AdConsentGateway>((ref) => UmpConsentGateway());

/// Gathered once per app run from the main shell; ad loads wait for it and are skipped without consent.
final adConsentProvider = FutureProvider<bool>((ref) async {
  final gateway = ref.read(adConsentGatewayProvider);
  final diagnostics = ref.read(adDiagnosticsProvider);
  try {
    final allowed = await gateway.gather();
    diagnostics.report('consent', ok: allowed, detail: gateway.lastError ?? '');
    return allowed;
  } catch (e) {
    diagnostics.report('consent', ok: false, detail: '$e');
    return false;
  }
});

// ------------------------------------------------------------------------------------------ purchases

class StoreProduct {
  const StoreProduct({required this.id, required this.price});

  final String id;

  /// Localised store price string ("₺149,99"); never computed client side.
  final String price;
}

enum StorePurchaseStatus { pending, purchased, restored, error, canceled }

class StorePurchase {
  const StorePurchase({
    required this.productId,
    required this.status,
    required this.store,
    required this.verificationData,
    this.handle,
  });

  final String productId;
  final StorePurchaseStatus status;

  /// `google` | `apple`.
  final String store;

  /// Play purchase token / StoreKit signed transaction (JWS).
  final String verificationData;

  /// Plugin object needed to finish the transaction.
  final Object? handle;
}

abstract interface class PurchaseGateway {
  Stream<List<StorePurchase>> get purchases;
  Future<StoreProduct?> loadProduct();
  Future<void> buy();
  Future<void> restore();

  /// Finishes/acknowledges a transaction after the server verified it.
  Future<void> complete(StorePurchase purchase);
}

class IapPurchaseGateway implements PurchaseGateway {
  final InAppPurchase _iap = InAppPurchase.instance;
  ProductDetails? _product;

  @override
  Stream<List<StorePurchase>> get purchases => _iap.purchaseStream.map(
    (list) => [
      for (final p in list)
        StorePurchase(
          productId: p.productID,
          status: switch (p.status) {
            PurchaseStatus.pending => StorePurchaseStatus.pending,
            PurchaseStatus.purchased => StorePurchaseStatus.purchased,
            PurchaseStatus.restored => StorePurchaseStatus.restored,
            PurchaseStatus.error => StorePurchaseStatus.error,
            PurchaseStatus.canceled => StorePurchaseStatus.canceled,
          },
          store: p.verificationData.source == 'app_store' ? 'apple' : 'google',
          verificationData: p.verificationData.serverVerificationData,
          handle: p,
        ),
    ],
  );

  @override
  Future<StoreProduct?> loadProduct() async {
    if (!await _iap.isAvailable()) return null;
    final res = await _iap.queryProductDetails({removeAdsProductId});
    if (res.productDetails.isEmpty) return null;
    final p = _product = res.productDetails.first;
    return StoreProduct(id: p.id, price: p.price);
  }

  @override
  Future<void> buy() async {
    final product = _product ?? (await loadProduct() == null ? null : _product);
    if (product == null) throw StateError('store unavailable');
    await _iap.buyNonConsumable(purchaseParam: PurchaseParam(productDetails: product));
  }

  @override
  Future<void> restore() => _iap.restorePurchases();

  @override
  Future<void> complete(StorePurchase purchase) async {
    final handle = purchase.handle;
    if (handle is PurchaseDetails && handle.pendingCompletePurchase) await _iap.completePurchase(handle);
  }
}

final purchaseGatewayProvider = Provider<PurchaseGateway>((ref) => IapPurchaseGateway());

// ------------------------------------------------------------------------------------------ dev simulations

String _b64url(List<int> bytes) => base64Url.encode(bytes).replaceAll('=', '');

String _randomId(String prefix) =>
    '${prefix}_${DateTime.now().millisecondsSinceEpoch}${Random().nextInt(1 << 20).toRadixString(36)}';

/// Signed transaction accepted by the backend `FakeAppleVerifier` (HS256 with `sha256("apple-dev:" + secret)`).
/// Dev only — the store verifier rejects it outside `purchase_verify_mode=fake`.
String devAppleSignedTransaction({String secret = devInternalSecret, String? transactionId}) {
  final id = transactionId ?? _randomId('dev');
  final key = utf8.encode(sha256.convert(utf8.encode('apple-dev:$secret')).toString());
  final header = _b64url(utf8.encode(jsonEncode({'alg': 'HS256', 'typ': 'JWT'})));
  final payload = _b64url(
    utf8.encode(
      jsonEncode({
        'bundleId': devAppleBundleId,
        'productId': removeAdsProductId,
        'transactionId': id,
        'originalTransactionId': id,
        'inAppOwnershipType': 'PURCHASED',
        'environment': 'Xcode',
      }),
    ),
  );
  final signature = _b64url(Hmac(sha256, key).convert(utf8.encode('$header.$payload')).bytes);
  return '$header.$payload.$signature';
}

/// Query parameters for the backend dev SSV callback (`GET /internal/ads/admob-ssv`, `DevSsvVerifier`):
/// `HMAC-SHA256(secret, query-before-&signature=)` in hex. The signed message is exactly the encoded query
/// the client sends, so the parameter order below must not change.
Map<String, String> devSsvQuery({
  required String userId,
  required String customData,
  String secret = devInternalSecret,
  String? transactionId,
}) {
  final params = <String, String>{
    'ad_network': 'dev',
    'ad_unit': 'dev_rewarded',
    'custom_data': customData,
    'reward_amount': '1',
    'reward_item': 'xp',
    'timestamp': '${DateTime.now().millisecondsSinceEpoch}',
    'transaction_id': transactionId ?? _randomId('devtx'),
    'user_id': userId,
  };
  final message = Uri(queryParameters: params).query;
  final signature = Hmac(sha256, utf8.encode(secret)).convert(utf8.encode(message)).toString();
  return {...params, 'signature': signature, 'key_id': 'dev'};
}
