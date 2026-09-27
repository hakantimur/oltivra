import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:oltivra/api/api_client.dart';
import 'package:oltivra/core/providers.dart';
import 'package:oltivra/features/store/ad_free_active_screen.dart';
import 'package:oltivra/features/store/privacy_ads_screen.dart';
import 'package:oltivra/features/store/remove_ads_screen.dart';
import 'package:oltivra/features/store/rewarded_offer_screen.dart';
import 'package:oltivra/features/store/store_services.dart';
import 'package:oltivra/l10n/strings.dart';
import 'package:oltivra/router/routes.dart';
import 'package:oltivra/session/session.dart';
import 'package:oltivra/theme/app_theme.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _Tokens implements TokenSource {
  @override
  Future<String?> appCheckToken() async => null;

  @override
  Future<String?> idToken({bool forceRefresh = false}) async => 'test:u1';
}

class _TestSession extends SessionController {
  _TestSession(this.value, this.onRefresh);

  final Session value;
  final void Function() onRefresh;

  @override
  Future<Session?> build() async => value;

  @override
  Future<void> refresh() async => onRefresh();
}

class _Call {
  _Call(this.method, this.path, this.body, this.query);

  final String method;
  final String path;
  final Map<String, dynamic> body;
  final Map<String, String> query;
}

/// Never touches the real ad SDK.
class _FakeRewardedAds implements RewardedAdGateway {
  _FakeRewardedAds(this.outcome);

  final RewardedAdOutcome outcome;
  final shown = <String>[];

  @override
  Future<RewardedAdOutcome> show({required String userId, required String customData}) async {
    shown.add('$userId|$customData');
    return outcome;
  }
}

class _FakeConsent implements AdConsentGateway {
  _FakeConsent({required this.required});

  final bool required;
  int opened = 0;

  @override
  Future<AdConsentState> refresh() async =>
      AdConsentState(privacyOptionsRequired: required, canRequestAds: true);

  @override
  Future<bool> gather() async => true;

  @override
  Future<void> showPrivacyOptions() async => opened++;
}

class _FakePurchases implements PurchaseGateway {
  final controller = StreamController<List<StorePurchase>>.broadcast();
  int buys = 0;

  @override
  Stream<List<StorePurchase>> get purchases => controller.stream;

  @override
  Future<StoreProduct?> loadProduct() async => null;

  @override
  Future<void> buy() async => buys++;

  @override
  Future<void> restore() async {}

  @override
  Future<void> complete(StorePurchase purchase) async {}
}

Session _session() => Session({
      'account': {
        'exists': true,
        'onboarding': {'consent': true, 'username': true, 'avatar': true, 'rename_required': false},
      },
      'profile': {'public_id': 'p1', 'username_display': 'mira_moves', 'avatar_id': 'av_001', 'remove_ads': false},
      'features': {'rewarded_xp': true},
    });

http.Response _json(Object body, [int status = 200]) =>
    http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});

typedef _Handler = http.Response Function(_Call call);

class _Harness {
  final calls = <_Call>[];
  int refreshes = 0;
}

Future<_Harness> _pump(
  WidgetTester tester, {
  required String location,
  required _Handler handler,
  AdConsentGateway? consent,
  RewardedAdGateway? ads,
}) async {
  GoogleFonts.config.allowRuntimeFetching = false;
  tester.view.physicalSize = const Size(900, 2400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  final h = _Harness();
  final client = MockClient((req) async {
    final body = req.body.isEmpty ? <String, dynamic>{} : (jsonDecode(req.body) as Map).cast<String, dynamic>();
    final call = _Call(req.method, req.url.path, body, req.url.queryParameters);
    h.calls.add(call);
    return handler(call);
  });
  final router = GoRouter(
    initialLocation: '/',
    routes: [
      GoRoute(path: '/', builder: (_, _) => const Scaffold(body: Text('ROOT'))),
      GoRoute(path: Routes.home, builder: (_, _) => const Scaffold(body: Text('HOME'))),
      GoRoute(path: '/rewards/:matchId', builder: (_, s) => RewardedOfferScreen(matchId: s.pathParameters['matchId']!)),
      GoRoute(path: Routes.removeAds, builder: (_, _) => const RemoveAdsScreen()),
      GoRoute(path: Routes.adFreeActive, builder: (_, _) => const AdFreeActiveScreen()),
      GoRoute(path: Routes.privacyAds, builder: (_, _) => const PrivacyAdsScreen()),
    ],
  );
  await tester.pumpWidget(ProviderScope(
    overrides: [
      sharedPrefsProvider.overrideWithValue(prefs),
      apiClientProvider.overrideWithValue(
          ApiClient(baseUrl: Uri.parse('http://api.test'), tokens: _Tokens(), client: client)),
      sessionProvider.overrideWith(() => _TestSession(_session(), () => h.refreshes++)),
      purchaseGatewayProvider.overrideWithValue(_FakePurchases()),
      adConsentGatewayProvider.overrideWithValue(consent ?? _FakeConsent(required: false)),
      rewardedAdGatewayProvider.overrideWithValue(ads ?? _FakeRewardedAds(RewardedAdOutcome.dismissed)),
    ],
    child: MaterialApp.router(
      theme: buildTheme(),
      routerConfig: router,
      supportedLocales: [for (final l in supportedLanguages) Locale(l)],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
    ),
  ));
  await tester.pumpAndSettle();
  router.push(location);
  await tester.pumpAndSettle();
  return h;
}

void main() {
  testWidgets('remove ads dev path verifies with the backend and opens the ad-free screen', (tester) async {
    final h = await _pump(tester, location: Routes.removeAds, handler: (call) {
      if (call.path == '/v1/purchases/verify/apple') {
        return _json({'remove_ads': true, 'state': 'ACTIVE', 'source_store': 'APP_STORE', 'purchase_state': 'PURCHASED'});
      }
      if (call.path == '/v1/purchases/entitlements') {
        return _json({'remove_ads': true, 'state': 'ACTIVE', 'source_store': 'APP_STORE'});
      }
      return _json({});
    });
    expect(find.text('Remove Ads Forever'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('remove_ads_buy')));
    await tester.pumpAndSettle();

    final verify = h.calls.singleWhere((c) => c.path == '/v1/purchases/verify/apple');
    expect((verify.body['signed_transaction'] as String).split('.'), hasLength(3));
    expect(h.refreshes, 1);
    expect(find.text('You’re ad-free'), findsOneWidget);
    expect(find.text('Verified via the App Store'), findsOneWidget);
  });

  testWidgets('remove ads restore finds a server entitlement', (tester) async {
    final h = await _pump(tester, location: Routes.removeAds, handler: (call) {
      if (call.path == '/v1/purchases/entitlements') {
        return _json({'remove_ads': true, 'state': 'ACTIVE', 'source_store': 'GOOGLE_PLAY'});
      }
      return _json({});
    });
    await tester.tap(find.byKey(const ValueKey('remove_ads_restore')));
    await tester.pumpAndSettle();
    expect(h.calls.where((c) => c.path.startsWith('/v1/purchases/verify')), isEmpty);
    expect(find.text('You’re ad-free'), findsOneWidget);
  });

  testWidgets('rewarded offer "not now" pops without starting an offer', (tester) async {
    final h = await _pump(tester, location: Routes.rewardedOffer('m1'), handler: (call) {
      if (call.path == '/v1/rewards/offers/m1') {
        return _json({'match_id': 'm1', 'state': 'ELIGIBLE', 'base_xp': 40, 'bonus_xp': 40});
      }
      return _json({});
    });
    expect(find.text('Double your match XP?'), findsOneWidget);
    expect(find.text('Watch an optional video to earn +40 XP.'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('reward_not_now')));
    await tester.pumpAndSettle();
    expect(find.text('ROOT'), findsOneWidget);
    expect(h.calls.where((c) => c.method == 'POST'), isEmpty);
  });

  testWidgets('rewarded offer dev simulation sends a signed SSV callback and shows the grant', (tester) async {
    var granted = false;
    final h = await _pump(tester, location: Routes.rewardedOffer('m1'), handler: (call) {
      if (call.method == 'GET' && call.path == '/v1/rewards/offers/m1') {
        return _json({'match_id': 'm1', 'state': granted ? 'GRANTED' : 'ELIGIBLE', 'base_xp': 40, 'bonus_xp': 40});
      }
      if (call.path == '/v1/rewards/offers/m1/start') {
        return _json({'match_id': 'm1', 'state': 'OFFERED', 'base_xp': 40, 'bonus_xp': 40, 'offer_id': 'o1',
            'custom_data': 'v1.o1.hash.m1.999.nonce.sig', 'ssv_user_id': 'hash', 'expires_at_ms': 999});
      }
      if (call.path == '/internal/ads/admob-ssv') {
        granted = true;
        return _json({'ok': true, 'granted': true, 'duplicate': false});
      }
      return _json({});
    });
    await tester.tap(find.byKey(const ValueKey('reward_simulate')));
    await tester.pumpAndSettle();
    final ssv = h.calls.singleWhere((c) => c.path == '/internal/ads/admob-ssv');
    expect(ssv.query['custom_data'], 'v1.o1.hash.m1.999.nonce.sig');
    expect(ssv.query['user_id'], 'hash');
    expect(ssv.query['signature'], isNotEmpty);
    expect(find.text('+40 XP added'), findsOneWidget);
    expect(h.refreshes, 1);
  });

  testWidgets('rewarded offer shows a dismissed video without granting', (tester) async {
    final ads = _FakeRewardedAds(RewardedAdOutcome.dismissed);
    final h = await _pump(
      tester,
      location: Routes.rewardedOffer('m1'),
      ads: ads,
      handler: (call) {
        if (call.path == '/v1/rewards/offers/m1/start') {
          return _json({'match_id': 'm1', 'state': 'OFFERED', 'base_xp': 40, 'bonus_xp': 40,
              'custom_data': 'cd', 'ssv_user_id': 'uh'});
        }
        return _json({'match_id': 'm1', 'state': 'ELIGIBLE', 'base_xp': 40, 'bonus_xp': 40});
      },
    );
    await tester.tap(find.byKey(const ValueKey('reward_watch')));
    await tester.pumpAndSettle();
    expect(ads.shown, ['uh|cd']);
    expect(h.calls.where((c) => c.path == '/internal/ads/admob-ssv'), isEmpty);
    expect(find.text('The video wasn’t finished, so no XP was added.'), findsOneWidget);
    expect(find.byKey(const ValueKey('reward_not_now')), findsOneWidget);
  });

  testWidgets('expired rewarded offer is handled', (tester) async {
    await _pump(tester, location: Routes.rewardedOffer('m1'), handler: (call) {
      if (call.path == '/v1/rewards/offers/m1/start') {
        return _json({'error': {'code': 'NOT_FOUND', 'detail': {'reason': 'reward_offer_expired'}}}, 404);
      }
      return _json({'match_id': 'm1', 'state': 'ELIGIBLE', 'base_xp': 40, 'bonus_xp': 40});
    });
    await tester.tap(find.byKey(const ValueKey('reward_watch')));
    await tester.pumpAndSettle();
    expect(find.text('This offer has expired.'), findsOneWidget);
  });

  testWidgets('privacy screen opens the UMP privacy options form when required', (tester) async {
    final consent = _FakeConsent(required: true);
    await _pump(tester, location: Routes.privacyAds, consent: consent,
        handler: (_) => _json({}));
    await tester.tap(find.byKey(const ValueKey('privacy_manage')));
    await tester.pumpAndSettle();
    expect(consent.opened, 1);
  });

  testWidgets('privacy screen stores the local personalised-ads choice when no form applies', (tester) async {
    await _pump(tester, location: Routes.privacyAds, handler: (_) => _json({}));
    await tester.tap(find.descendant(of: find.byKey(const ValueKey('privacy_personalized')), matching: find.byType(Switch)));
    await tester.pumpAndSettle();
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getBool(personalizedAdsPrefKey), isFalse);
  });

  test('dev signers are deterministic for a fixed transaction', () {
    // Verified against the backend FakeAppleVerifier("dev-internal-secret").
    expect(
      devAppleSignedTransaction(transactionId: 'dev_1'),
      'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJidW5kbGVJZCI6ImNvbS5vbHRpdnJhLmFwcCIsInByb2R1Y3RJZCI6InJlbW92ZV9hZHNf'
      'Zm9yZXZlciIsInRyYW5zYWN0aW9uSWQiOiJkZXZfMSIsIm9yaWdpbmFsVHJhbnNhY3Rpb25JZCI6ImRldl8xIiwiaW5BcHBPd25lcnNoaXBU'
      'eXBlIjoiUFVSQ0hBU0VEIiwiZW52aXJvbm1lbnQiOiJYY29kZSJ9.zAjKJWyJrbM3OXzh9pHMl0ekgLGbE4GUOk3MR2mUVHg',
    );
    final q = devSsvQuery(userId: 'u', customData: 'cd', transactionId: 't');
    expect(q.keys.toList().sublist(q.length - 2), ['signature', 'key_id']);
    expect(q['signature'], hasLength(64));
  });
}
