import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:oltivra/api/api_client.dart';
import 'package:oltivra/auth/auth_service.dart';
import 'package:oltivra/core/providers.dart';
import 'package:oltivra/features/home/choose_battle_screen.dart';
import 'package:oltivra/features/home/finding_match_screen.dart';
import 'package:oltivra/features/home/home_screen.dart';
import 'package:oltivra/features/home/match_ready_screen.dart';
import 'package:oltivra/live/match_live_source.dart';
import 'package:oltivra/live/match_snapshot.dart';
import 'package:oltivra/session/session.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _Tokens implements TokenSource {
  @override
  Future<String?> appCheckToken() async => null;

  @override
  Future<String?> idToken({bool forceRefresh = false}) async => 'test:u1';
}

class _FixedSession extends SessionController {
  _FixedSession(this.value);

  final Session? value;

  @override
  Future<Session?> build() async => value;
}

class _FakeLive implements MatchLiveSource {
  final controller = StreamController<LiveUpdate>.broadcast();

  @override
  Stream<LiveUpdate> watch(String matchId) => controller.stream;
}

Session _session({bool survival = true, List<String> categories = const [], Map<String, dynamic>? runtime}) =>
    Session({
      'server_time_ms': DateTime.now().millisecondsSinceEpoch,
      'account': {
        'exists': true,
        'onboarding': {'consent': true, 'username': true, 'avatar': true, 'rename_required': false},
      },
      'profile': {
        'username_display': 'mira_moves',
        'avatar_id': 'av_001',
        'frame_id': 'frame_none',
        'level': 12,
        'league': 'SILVER',
        'question_language': 'en',
      },
      'runtime': runtime ?? {'state': 'IDLE'},
      'features': {'survival': survival, 'category_queue_ids': categories, 'rewarded_xp': false},
    });

const _config = {
  'quick': {'questions': 10, 'seconds': 11, 'wrong_penalty': 5},
  'survival': {'seconds': 11},
};

typedef _Handler = FutureOr<Object?> Function(http.Request req);

String _stub(GoRouterState s) => '${s.uri.path}${s.uri.hasQuery ? '?${s.uri.query}' : ''}';

Future<void> _pumpApp(
  WidgetTester tester, {
  required String initial,
  required _Handler handler,
  Session? session,
  List<String>? calls,
  MatchLiveSource? live,
  bool realQueue = true,
}) async {
  tester.view.physicalSize = const Size(1200, 2800);
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  final api = ApiClient(
    baseUrl: Uri.parse('http://api.test'),
    tokens: _Tokens(),
    client: MockClient((req) async {
      calls?.add('${req.method} ${req.url.path}');
      if (req.url.path == '/v1/client-config') return http.Response(jsonEncode(_config), 200);
      final res = await handler(req);
      if (res is http.Response) return res;
      if (res == null) return http.Response('{"error": {"code": "NOT_FOUND"}}', 404);
      return http.Response(jsonEncode(res), 200);
    }),
  );
  final router = GoRouter(
    initialLocation: initial,
    routes: [
      GoRoute(path: '/home', builder: (_, _) => const HomeScreen()),
      GoRoute(path: '/play', builder: (_, s) => const ChooseBattleScreen()),
      GoRoute(
        path: '/play/queue/:mode',
        builder: (_, s) => realQueue
            ? FindingMatchScreen(
                mode: s.pathParameters['mode']!.toUpperCase(), categoryId: s.uri.queryParameters['category'])
            : Scaffold(body: Text('QUEUE:${_stub(s)}')),
      ),
      GoRoute(path: '/match/:id/ready', builder: (_, s) => MatchReadyScreen(matchId: s.pathParameters['id']!)),
      GoRoute(path: '/match/:id', builder: (_, s) => Scaffold(body: Text('MATCH:${s.pathParameters['id']}'))),
      GoRoute(path: '/missions', builder: (_, s) => const Scaffold(body: Text('MISSIONS'))),
    ],
  );
  await tester.pumpWidget(ProviderScope(
    overrides: [
      sharedPrefsProvider.overrideWithValue(prefs),
      authStateProvider.overrideWithValue(const AsyncValue.data(AuthUser(uid: 'u1', provider: 'google'))),
      apiClientProvider.overrideWithValue(api),
      sessionProvider.overrideWith(() => _FixedSession(session ?? _session())),
      if (live != null) matchLiveSourceProvider.overrideWithValue(live),
    ],
    child: MaterialApp.router(routerConfig: router),
  ));
  await _settle(tester);
}

/// Lets mocked HTTP futures complete without waiting for infinite animations.
Future<void> _settle(WidgetTester tester, [int frames = 10]) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

void main() {
  setUpAll(() => GoogleFonts.config.allowRuntimeFetching = false);

  group('FindingMatchScreen', () {
    testWidgets('pings, joins, polls status and navigates to match ready when MATCHED', (tester) async {
      final calls = <String>[];
      Map<String, dynamic>? joinBody;
      await _pumpApp(
        tester,
        initial: '/play/queue/quick',
        calls: calls,
        handler: (req) {
          final now = DateTime.now().millisecondsSinceEpoch;
          switch ('${req.method} ${req.url.path}') {
            case 'GET /v1/ping':
              return {'server_received_at_ms': now, 'server_responded_at_ms': now};
            case 'POST /v1/matchmaking/quick/join':
              joinBody = jsonDecode(req.body) as Map<String, dynamic>;
              return {
                'state': 'QUEUED',
                'ticket_id': 't1',
                'mode': 'QUICK',
                'human_fill_at_ms': now + 800,
                'expires_at_ms': now + 60000,
                'next_poll_at_ms': now + 800,
                'server_time_ms': now,
              };
            case 'GET /v1/matchmaking/status':
              return {
                'state': 'MATCHED',
                'server_time_ms': now,
                'match': {'match_id': 'm1', 'mode': 'QUICK', 'rtdb_shard_id': 's0'},
              };
          }
          return null;
        },
        live: _FakeLive(),
      );
      expect(find.text('Finding your Quick Battle'), findsOneWidget);
      expect(find.text('mira_moves'), findsOneWidget);
      expect(calls.where((c) => c == 'GET /v1/ping').length, 5);
      expect(calls, contains('POST /v1/matchmaking/quick/join'));
      expect(joinBody!['median_rtt_ms'], isA<int>());
      expect(joinBody!.containsKey('category_id'), isFalse);
      expect(calls, isNot(contains('GET /v1/matchmaking/status')));

      await tester.pump(const Duration(milliseconds: 1200));
      await _settle(tester);
      expect(calls, contains('GET /v1/matchmaking/status'));
      expect(find.text('Countdown'), findsOneWidget); // MatchReadyScreen app bar
      expect(find.textContaining(RegExp('bot|CPU|AI', caseSensitive: false)), findsNothing);
    });

    testWidgets('cancel leaves the queue and returns to Play', (tester) async {
      final calls = <String>[];
      await _pumpApp(
        tester,
        initial: '/play/queue/survival',
        calls: calls,
        handler: (req) {
          final now = DateTime.now().millisecondsSinceEpoch;
          switch ('${req.method} ${req.url.path}') {
            case 'GET /v1/ping':
              return {};
            case 'POST /v1/matchmaking/survival/join':
              return {'state': 'QUEUED', 'next_poll_at_ms': now + 4000, 'expires_at_ms': now + 60000,
                'server_time_ms': now};
            case 'DELETE /v1/matchmaking/survival/leave':
              return {'state': 'CANCELLED', 'ticket_id': 't1'};
          }
          return null;
        },
      );
      expect(find.text('Finding your Survival match'), findsOneWidget);
      await tester.tap(find.text('Cancel'));
      await _settle(tester);
      expect(calls, contains('DELETE /v1/matchmaking/survival/leave'));
      expect(find.text('Choose your battle'), findsOneWidget);
    });

    testWidgets('an expired ticket offers a retry', (tester) async {
      await _pumpApp(
        tester,
        initial: '/play/queue/quick',
        handler: (req) {
          switch ('${req.method} ${req.url.path}') {
            case 'GET /v1/ping':
              return {};
            case 'POST /v1/matchmaking/quick/join':
              return {'state': 'EXPIRED', 'ticket_id': 't1'};
          }
          return null;
        },
      );
      expect(find.text('No match came together this time.'), findsOneWidget);
      expect(find.text('Search again'), findsOneWidget);
    });
  });

  group('HomeScreen', () {
    testWidgets('renders the first two daily missions and weekly rank from the API', (tester) async {
      final now = DateTime.now().millisecondsSinceEpoch;
      await _pumpApp(
        tester,
        initial: '/home',
        handler: (req) => switch (req.url.path) {
          '/v1/missions/daily' => {
              'period_id': 'D2026-09-27',
              'ends_at_ms': now + 8 * 3600 * 1000 + 60000,
              'missions': [
                {'mission_id': 'a', 'template_id': 'play_quick_3', 'target': 3, 'progress': 1, 'completed': false},
                {'mission_id': 'b', 'template_id': 'answer_correct_10', 'target': 10, 'progress': 10,
                  'completed': true},
                {'mission_id': 'c', 'template_id': 'send_reactions_5', 'target': 5, 'progress': 0, 'completed': false},
              ],
            },
          '/v1/league' => {'league': 'SILVER', 'progress': 0.4, 'next_league': 'GOLD', 'ranked_weekly_xp': 320},
          '/v1/leaderboards/weekly' => {
              'entries': [],
              'me': {'rank': 142, 'league': 'SILVER', 'ranked_weekly_xp': 320},
            },
          _ => null,
        },
      );
      expect(find.text('mira_moves'), findsOneWidget);
      expect(find.text('Join a Quick Battle'), findsOneWidget);
      expect(find.text('Try Survival'), findsOneWidget);
      expect(find.text('Play 3 Quick Battles'), findsOneWidget);
      expect(find.text('1/3'), findsOneWidget);
      expect(find.text('Answer 10 questions correctly'), findsOneWidget);
      expect(find.text('Send 5 reactions'), findsNothing);
      expect(find.text('Resets in 8h'), findsOneWidget);
      expect(find.text('#142'), findsOneWidget);
      expect(find.text('320 XP'), findsOneWidget);
      expect(find.text('Rejoin'), findsNothing);
    });

    testWidgets('shows a rejoin banner for an active match and hides missing weekly data', (tester) async {
      await _pumpApp(
        tester,
        initial: '/home',
        session: _session(survival: false, runtime: {'state': 'MATCH_ACTIVE', 'match_id': 'm9'}),
        handler: (req) => switch (req.url.path) {
          '/v1/missions/daily' => {'ends_at_ms': 0, 'missions': []},
          _ => null,
        },
      );
      expect(find.text('Rejoin'), findsOneWidget);
      expect(find.text('Try Survival'), findsNothing);
      expect(find.text('This week'), findsNothing);
      await tester.tap(find.text('Rejoin'));
      await _settle(tester);
      expect(find.text('MATCH:m9'), findsOneWidget);
    });
  });

  group('ChooseBattleScreen', () {
    testWidgets('hides Survival when the feature is disabled', (tester) async {
      await _pumpApp(tester, initial: '/play', session: _session(survival: false), handler: (_) => null);
      expect(find.text('Choose your battle'), findsOneWidget);
      expect(find.text('Play Quick Battle'), findsOneWidget);
      expect(find.text('Play Survival'), findsNothing);
      expect(find.text('4 players · 10 questions · 11 seconds each'), findsOneWidget);
    });

    testWidgets('category selector passes the category to the queue route', (tester) async {
      await _pumpApp(
        tester,
        initial: '/play',
        session: _session(categories: ['history', 'sports']),
        handler: (_) => null,
        realQueue: false,
      );
      expect(find.text('Play Survival'), findsOneWidget);
      expect(find.text('Mixed'), findsOneWidget);
      await tester.tap(find.text('History'));
      await _settle(tester, 3);
      await tester.ensureVisible(find.text('Play Quick Battle'));
      await tester.tap(find.text('Play Quick Battle'));
      await _settle(tester, 3);
      expect(find.text('QUEUE:/play/queue/quick?category=history'), findsOneWidget);
    });
  });

  group('MatchReadyScreen', () {
    testWidgets('shows the roster and moves to the match when round 1 goes live', (tester) async {
      final live = _FakeLive();
      await _pumpApp(tester, initial: '/match/m1/ready', handler: (_) => null, live: live);
      final now = DateTime.now().millisecondsSinceEpoch;
      Map<String, dynamic> participant(String name, int slot) =>
          {'display_name': name, 'avatar_id': 'av_00${slot + 1}', 'slot': slot, 'active': true};
      final public = {
        'match_id': 'm1',
        'mode': 'QUICK',
        'language': 'en',
        'state': 'ROUND_LOADING',
        'round_number': 1,
        'starts_at_ms': now + 60000,
        'next_server_event_at_ms': now + 60000,
        'total_normal_rounds': 10,
        'participants': {
          'p1': participant('mira_moves', 0),
          'p2': participant('kevin_q', 1),
          'p3': participant('sora_7', 2),
          'p4': participant('elena_z', 3),
        },
      };
      live.controller.add(LiveUpdate(
          MatchSnapshot(matchId: 'm1', public: public, private: {'pid': 'p1'}), LiveHealth.connected));
      await _settle(tester);
      expect(find.text('kevin_q'), findsOneWidget);
      expect(find.text('elena_z'), findsOneWidget);
      expect(find.text('You'), findsOneWidget);
      expect(find.text('Quick Battle · English questions'), findsOneWidget);

      live.controller.add(LiveUpdate(
          MatchSnapshot(matchId: 'm1', public: {...public, 'state': 'ROUND_ACTIVE'}, private: {'pid': 'p1'}),
          LiveHealth.connected));
      await _settle(tester);
      expect(find.text('MATCH:m1'), findsOneWidget);
    });
  });
}
