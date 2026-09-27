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
import 'package:oltivra/features/settings/blocked_players_screen.dart';
import 'package:oltivra/features/settings/delete_account_screen.dart';
import 'package:oltivra/features/settings/language_screen.dart';
import 'package:oltivra/features/settings/report_player_screen.dart';
import 'package:oltivra/features/settings/settings_screen.dart';
import 'package:oltivra/l10n/strings.dart';
import 'package:oltivra/l10n/tables/settings.dart';
import 'package:oltivra/l10n/tables/store.dart';
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
  _TestSession(this.value);

  final Session value;

  @override
  Future<Session?> build() async => value;
}

class _Call {
  _Call(this.method, this.path, this.body, this.query);

  final String method;
  final String path;
  final Map<String, dynamic> body;
  final Map<String, String> query;
}

Json _profile([Json extra = const {}]) => {
      'public_id': 'p1',
      'username_display': 'mira_moves',
      'avatar_id': 'av_001',
      'frame_id': 'frame_none',
      'frame_ids': ['frame_none'],
      'level': 4,
      'league': 'SILVER',
      'question_language': 'en',
      'ui_language': 'en',
      'notifications': {'friend_requests': true, 'challenges': true, 'league': true, 'leaderboard': true,
          'missions': true},
      'onboarding': {'consent': true, 'username': true, 'avatar': true, 'rename_required': false},
      ...extra,
    };

Session _session() => Session({
      'account': {
        'exists': true,
        'onboarding': {'consent': true, 'username': true, 'avatar': true, 'rename_required': false},
      },
      'profile': _profile(),
      'question_languages': ['en'],
      'ui_languages': ['en', 'tr'],
      'features': {'rewarded_xp': true},
    });

http.Response _json(Object body, [int status = 200]) =>
    http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});

typedef _Handler = http.Response Function(_Call call);

class _Harness {
  final calls = <_Call>[];
  late ProviderContainer container;
}

Future<_Harness> _pump(
  WidgetTester tester, {
  required Widget screen,
  required _Handler handler,
  List overrides = const [],
}) async {
  GoogleFonts.config.allowRuntimeFetching = false;
  tester.view.physicalSize = const Size(900, 2400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  final harness = _Harness();
  final client = MockClient((req) async {
    final body = req.body.isEmpty ? <String, dynamic>{} : (jsonDecode(req.body) as Map).cast<String, dynamic>();
    final call = _Call(req.method, req.url.path, body, req.url.queryParameters);
    harness.calls.add(call);
    return handler(call);
  });
  final router = GoRouter(
    initialLocation: '/',
    routes: [
      GoRoute(path: '/', builder: (_, _) => const Scaffold(body: Text('ROOT'))),
      GoRoute(path: '/screen', builder: (_, _) => screen),
      GoRoute(path: '/settings', builder: (_, _) => const Scaffold(body: Text('SETTINGS'))),
    ],
  );
  await tester.pumpWidget(ProviderScope(
    overrides: [
      sharedPrefsProvider.overrideWithValue(prefs),
      apiClientProvider.overrideWithValue(ApiClient(baseUrl: Uri.parse('http://api.test'), tokens: _Tokens(),
          client: client)),
      sessionProvider.overrideWith(() => _TestSession(_session())),
      ...overrides,
    ],
    child: Consumer(builder: (context, ref, _) {
      return MaterialApp.router(
        theme: buildTheme(),
        routerConfig: router,
        locale: ref.watch(localeProvider),
        supportedLocales: [for (final l in supportedLanguages) Locale(l)],
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
      );
    }),
  ));
  harness.container = ProviderScope.containerOf(tester.element(find.text('ROOT')));
  await harness.container.read(sessionProvider.future);
  router.push('/screen');
  await tester.pumpAndSettle();
  return harness;
}

void main() {
  testWidgets('settings lists sections and toggles a notification preference', (tester) async {
    final h = await _pump(tester, screen: const SettingsScreen(), handler: (call) {
      if (call.method == 'PATCH' && call.path == '/v1/profile/preferences') {
        return _json({'profile': _profile({'notifications': {'friend_requests': false, 'challenges': true,
            'league': true, 'leaderboard': true, 'missions': true}})});
      }
      return _json({});
    });
    expect(find.text('Edit profile'), findsOneWidget);
    expect(find.text('Blocked players'), findsOneWidget);
    expect(find.text('Delete shared account'), findsOneWidget);
    await tester.tap(find.byType(Switch).first);
    await tester.pumpAndSettle();
    final patch = h.calls.singleWhere((c) => c.method == 'PATCH');
    expect(patch.body['notifications'], {'friend_requests': false});
    final session = h.container.read(sessionProvider).value!;
    expect((session.profile!['notifications'] as Map)['friend_requests'], isFalse);
  });

  testWidgets('language change patches preferences and updates the locale', (tester) async {
    final h = await _pump(tester, screen: const LanguageScreen(), handler: (call) {
      if (call.method == 'PATCH') return _json({'profile': _profile({'ui_language': 'tr'})});
      return _json({});
    });
    expect(find.text('QUESTION LANGUAGE'), findsOneWidget);
    await tester.tap(find.text('Türkçe').first);
    await tester.pumpAndSettle();
    final patch = h.calls.singleWhere((c) => c.method == 'PATCH' && c.path == '/v1/profile/preferences');
    expect(patch.body['ui_language'], 'tr');
    expect(h.container.read(localeProvider), const Locale('tr'));
    expect(h.container.read(sessionProvider).value!.uiLanguage, 'tr');
    // The screen re-renders in Turkish.
    expect(find.textContaining('Menüleri'), findsOneWidget);
  });

  testWidgets('blocked players list unblocks with DELETE', (tester) async {
    final h = await _pump(tester, screen: const BlockedPlayersScreen(), handler: (call) {
      if (call.method == 'GET' && call.path == '/v1/blocks') {
        return _json({'blocked': [
          {'public_id': 'p2', 'username': 'toxic_troll', 'avatar_id': 'av_003'},
          {'public_id': 'p3', 'username': 'spammer_x', 'avatar_id': 'av_004'},
        ]});
      }
      if (call.method == 'DELETE') return _json({'blocked': false});
      return _json({});
    });
    expect(find.text('toxic_troll'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('unblock_p2')));
    await tester.pumpAndSettle();
    expect(h.calls.where((c) => c.method == 'DELETE' && c.path == '/v1/blocks/p2'), hasLength(1));
    expect(find.text('toxic_troll'), findsNothing);
    expect(find.text('spammer_x'), findsOneWidget);
  });

  testWidgets('report submits the selected reason, optionally blocks, then confirms', (tester) async {
    final h = await _pump(
      tester,
      screen: const ReportPlayerScreen(publicId: 'p9', matchId: 'm1'),
      handler: (call) {
        if (call.path == '/v1/users/p9') {
          return _json({'profile': {'username_display': 'shadow_spammer', 'avatar_id': 'av_002'},
              'relationship': {'blocked': false}});
        }
        if (call.path == '/v1/player-reports') return _json({'report_id': 'r1', 'status': 'RECEIVED'});
        if (call.path == '/v1/blocks/p9') return _json({'blocked': true});
        return _json({});
      },
    );
    expect(find.text('shadow_spammer'), findsOneWidget);
    // Submit is disabled until a reason is chosen.
    await tester.tap(find.byKey(const ValueKey('report_submit')));
    await tester.pumpAndSettle();
    expect(h.calls.where((c) => c.path == '/v1/player-reports'), isEmpty);

    await tester.tap(find.byKey(const ValueKey('reason_HARASSMENT')));
    await tester.tap(find.byKey(const ValueKey('report_block_toggle')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('report_submit')));
    await tester.pumpAndSettle();

    final report = h.calls.singleWhere((c) => c.path == '/v1/player-reports');
    expect(report.body['reason'], 'HARASSMENT');
    expect(report.body['target_public_id'], 'p9');
    expect(report.body['match_id'], 'm1');
    expect(h.calls.where((c) => c.method == 'POST' && c.path == '/v1/blocks/p9'), hasLength(1));
    expect(find.text('Thanks — we’ll review this.'), findsOneWidget);
  });

  testWidgets('delete account requires typed confirmation and a fresh sign-in', (tester) async {
    var freshSignIns = 0;
    final h = await _pump(
      tester,
      screen: const DeleteAccountScreen(),
      overrides: [freshSignInProvider.overrideWithValue((_) async => freshSignIns++)],
      handler: (call) {
        if (call.method == 'GET' && call.path == '/v1/account/deletion') return _json({'status': 'NONE'});
        if (call.method == 'DELETE' && call.path == '/v1/account') return _json({'status': 'COMPLETED'});
        return _json({});
      },
    );
    await tester.tap(find.byKey(const ValueKey('delete_continue')));
    await tester.pumpAndSettle();

    // Disabled until the confirmation word is typed.
    await tester.tap(find.byKey(const ValueKey('delete_confirm')));
    await tester.pumpAndSettle();
    expect(h.calls.where((c) => c.method == 'DELETE'), isEmpty);
    expect(freshSignIns, 0);

    await tester.enterText(find.byKey(const ValueKey('delete_confirm_field')), 'delete');
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('delete_confirm')));
    await tester.pumpAndSettle();

    expect(freshSignIns, 1);
    expect(h.calls.where((c) => c.method == 'DELETE' && c.path == '/v1/account'), hasLength(1));
    expect(find.text('Your account was deleted'), findsOneWidget);
  });

  testWidgets('keep my account leaves the deletion flow', (tester) async {
    final h = await _pump(tester, screen: const DeleteAccountScreen(),
        handler: (call) => _json({'status': 'NONE'}));
    await tester.tap(find.byKey(const ValueKey('delete_keep')));
    await tester.pumpAndSettle();
    expect(find.text('ROOT'), findsOneWidget);
    expect(h.calls.where((c) => c.method == 'DELETE'), isEmpty);
  });

  test('confirmation word matches across case and Turkish dotted I', () {
    expect(confirmWordMatches(' delete ', 'DELETE'), isTrue);
    expect(confirmWordMatches('sil', 'SİL'), isTrue);
    expect(confirmWordMatches('SIL', 'SİL'), isTrue);
    expect(confirmWordMatches('', 'DELETE'), isFalse);
    expect(confirmWordMatches('delet', 'DELETE'), isFalse);
  });

  test('settings and store tables have matching en/tr keys', () {
    for (final table in [settingsStrings, storeStrings]) {
      expect(table['tr']!.keys.toSet(), table['en']!.keys.toSet());
    }
  });
}
