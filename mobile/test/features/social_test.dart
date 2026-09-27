import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:oltivra/api/api_client.dart';
import 'package:oltivra/core/providers.dart';
import 'package:oltivra/features/social/challenge_lobby_screen.dart';
import 'package:oltivra/features/social/find_players_screen.dart';
import 'package:oltivra/features/social/friends_screen.dart';
import 'package:oltivra/features/social/incoming_challenge_screen.dart';
import 'package:oltivra/features/social/player_profile_screen.dart';
import 'package:oltivra/session/session.dart';
import 'package:oltivra/theme/app_theme.dart';

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

typedef _Handler = Object Function(http.Request request);

/// Records every request and answers from [handler] (a JSON-encodable body, or an [http.Response]).
class _Backend {
  _Backend(this.handler);

  final _Handler handler;
  final List<http.Request> requests = [];

  MockClient get client => MockClient((req) async {
        requests.add(req);
        final out = handler(req);
        if (out is http.Response) return out;
        return http.Response(jsonEncode(out), 200, headers: {'content-type': 'application/json'});
      });

  Iterable<http.Request> called(String method, String path) =>
      requests.where((r) => r.method == method && r.url.path == path);
}

Json _card(String pid, String name, {String league = 'SILVER', int level = 7}) =>
    {'public_id': pid, 'username': name, 'avatar_id': 'av_001', 'frame_id': 'frame_none', 'league': league,
     'level': level};

Future<void> _pump(WidgetTester tester, Widget screen, _Backend backend) async {
  tester.view.physicalSize = const Size(1200, 2600);
  tester.view.devicePixelRatio = 3;
  addTearDown(tester.view.reset);
  final router = GoRouter(
    initialLocation: '/',
    routes: [
      GoRoute(path: '/', builder: (_, _) => screen),
      GoRoute(path: '/match/:id/ready', builder: (_, s) => Scaffold(body: Text('READY ${s.pathParameters['id']}'))),
      GoRoute(path: '/players/:pid', builder: (_, s) => Scaffold(body: Text('PROFILE ${s.pathParameters['pid']}'))),
      GoRoute(path: '/challenge/new', builder: (_, _) => const Scaffold(body: Text('NEW CHALLENGE'))),
      GoRoute(path: '/challenge/lobby/:id', builder: (_, s) => Scaffold(body: Text('LOBBY ${s.pathParameters['id']}'))),
      GoRoute(path: '/report/:pid', builder: (_, _) => const Scaffold(body: Text('REPORT'))),
      GoRoute(path: '/social', builder: (_, _) => const Scaffold(body: Text('SOCIAL'))),
      GoRoute(path: '/social/find', builder: (_, _) => const Scaffold(body: Text('FIND'))),
      GoRoute(path: '/social/requests', builder: (_, _) => const Scaffold(body: Text('REQUESTS'))),
    ],
  );
  await tester.pumpWidget(ProviderScope(
    overrides: [
      apiClientProvider.overrideWithValue(
          ApiClient(baseUrl: Uri.parse('http://api.test'), tokens: _Tokens(), client: backend.client)),
      sessionProvider.overrideWith(() => _FixedSession(Session({
            'profile': {'public_id': 'pme', 'username_display': 'mira_moves', 'question_language': 'en'},
          }))),
    ],
    child: MaterialApp.router(theme: buildTheme(), routerConfig: router),
  ));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
}

void main() {
  setUpAll(() => GoogleFonts.config.allowRuntimeFetching = false);

  testWidgets('friends list renders friends, request badge and challenge actions', (tester) async {
    final backend = _Backend((req) => {
          'schema_version': 1,
          'friends': [
            {..._card('p1', 'kevin_q'), 'can_challenge': true},
            {..._card('p2', 'elena_z', league: 'GOLD'), 'can_challenge': false},
          ],
          'incoming_requests': [
            {'request_id': 'r1', ..._card('p3', 'tariq_9')},
          ],
          'outgoing_requests': [],
        });
    await _pump(tester, const FriendsScreen(), backend);

    expect(backend.called('GET', '/v1/friends'), hasLength(1));
    expect(find.text('kevin_q'), findsOneWidget);
    expect(find.text('elena_z'), findsOneWidget);
    expect(find.text('Silver'), findsOneWidget);
    expect(find.text('Gold'), findsOneWidget);
    expect(find.text('Friend requests'), findsOneWidget); // requests summary card
    expect(find.text('Challenge'), findsOneWidget);
    expect(find.text('Busy'), findsOneWidget);

    await tester.tap(find.text('kevin_q'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('PROFILE p1'), findsOneWidget);
  });

  testWidgets('friends empty state', (tester) async {
    final backend = _Backend((req) =>
        {'schema_version': 1, 'friends': [], 'incoming_requests': [], 'outgoing_requests': []});
    await _pump(tester, const FriendsScreen(), backend);
    expect(find.text('No friends yet'), findsOneWidget);
  });

  testWidgets('search is debounced, sends the username query and can send a request', (tester) async {
    final backend = _Backend((req) {
      if (req.url.path == '/v1/users/search') {
        return {
          'schema_version': 1,
          'results': [
            {..._card('p5', 'alexa_run', league: 'BRONZE'), 'relationship': 'NONE'},
            {..._card('p6', 'alex_b'), 'relationship': 'FRIEND'},
          ],
        };
      }
      if (req.url.path == '/v1/friends/requests') return {'schema_version': 1, 'relationship': 'REQUEST_SENT'};
      return {'schema_version': 1, 'friends': [], 'incoming_requests': [], 'outgoing_requests': []};
    });
    await _pump(tester, const FindPlayersScreen(), backend);

    await tester.enterText(find.byKey(const ValueKey('social-search-field')), 'al');
    await tester.pump(const Duration(milliseconds: 100));
    await tester.enterText(find.byKey(const ValueKey('social-search-field')), 'alex');
    await tester.pump(const Duration(milliseconds: 450));
    await tester.pump();

    final searches = backend.called('GET', '/v1/users/search').toList();
    expect(searches, hasLength(1));
    expect(searches.single.url.queryParameters['username'], 'alex');
    expect(find.text('alexa_run'), findsOneWidget);
    expect(find.text('alex_b'), findsOneWidget);

    await tester.tap(find.text('Add friend'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    final post = backend.called('POST', '/v1/friends/requests').single;
    expect((jsonDecode(post.body) as Map)['target_public_id'], 'p5');
    expect(find.text('Request sent'), findsOneWidget);
  });

  testWidgets('profile block flow confirms and calls the block endpoint', (tester) async {
    var blocked = false;
    final backend = _Backend((req) {
      if (req.method == 'POST' && req.url.path == '/v1/blocks/p9') {
        blocked = true;
        return {'schema_version': 1, 'blocked': true};
      }
      if (req.url.path == '/v1/users/p9') {
        return {
          'schema_version': 1,
          'profile': {
            'public_id': 'p9', 'username_display': 'kevin_q', 'avatar_id': 'av_002', 'frame_id': 'frame_none',
            'featured_badge_ids': [], 'league': 'SILVER', 'level': 14, 'quick_best_ranked_win_streak': 7,
            'survival_ranked_crowns_lifetime': 3, 'quick_ranked_wins_lifetime': 48,
          },
          'relationship': {'friend': true, 'outgoing_request': false, 'incoming_request': false, 'blocked': blocked},
        };
      }
      return {'schema_version': 1, 'friends': [], 'incoming_requests': [], 'outgoing_requests': []};
    });
    await _pump(tester, const PlayerProfileScreen(publicId: 'p9'), backend);

    expect(find.text('kevin_q'), findsOneWidget);
    expect(find.text('48'), findsOneWidget);
    expect(find.text('Challenge'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('profile-menu')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    await tester.tap(find.text('Block').last);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('Block kevin_q?'), findsOneWidget);
    await tester.tap(find.widgetWithText(TextButton, 'Block'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    expect(backend.called('POST', '/v1/blocks/p9'), hasLength(1));
    expect(find.text('You blocked this player'), findsOneWidget);
    expect(find.text('Unblock'), findsOneWidget);
  });

  testWidgets('lobby renders members and navigates to match ready when MATCHED', (tester) async {
    var polls = 0;
    Json party(String state, {String? matchId}) => {
          'schema_version': 1, 'party_id': 'party1', 'kind': 'CHALLENGE', 'mode': 'QUICK',
          'question_language': 'en', 'state': state, 'expires_at_ms': DateTime.now().millisecondsSinceEpoch + 50000,
          'min_humans': 2, 'match_id': matchId,
          'members': [
            {..._card('pme', 'mira_moves'), 'status': 'ACCEPTED', 'is_host': true, 'is_you': true},
            {..._card('p1', 'kevin_q'), 'status': 'ACCEPTED', 'is_host': false, 'is_you': false},
            {..._card('p2', 'elena_z'), 'status': 'INVITED', 'is_host': false, 'is_you': false},
          ],
        };
    final backend = _Backend((req) {
      if (req.url.path == '/v1/parties/party1') {
        polls++;
        return polls < 2 ? party('READY') : party('MATCHED', matchId: 'm42');
      }
      return http.Response('{}', 404);
    });
    await _pump(tester, const ChallengeLobbyScreen(partyId: 'party1'), backend);

    expect(find.text('mira_moves'), findsOneWidget);
    expect(find.text('kevin_q'), findsOneWidget);
    expect(find.text('elena_z'), findsOneWidget);
    expect(find.text('Host'), findsOneWidget);
    expect(find.text('Invited'), findsOneWidget);
    expect(find.text('Open place'), findsOneWidget);
    expect(find.textContaining('Question language: English'), findsOneWidget);
    expect(find.byKey(const ValueKey('lobby-start')), findsOneWidget);

    await tester.pump(const Duration(seconds: 2));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('READY m42'), findsOneWidget);
  });

  testWidgets('composer creates a challenge with the selected friends', (tester) async {
    final backend = _Backend((req) {
      if (req.url.path == '/v1/challenges') {
        return {
          'schema_version': 1, 'party_id': 'party7', 'kind': 'CHALLENGE', 'mode': 'QUICK',
          'question_language': 'en', 'state': 'WAITING',
          'expires_at_ms': DateTime.now().millisecondsSinceEpoch + 60000, 'min_humans': 2, 'match_id': null,
          'members': [
            {..._card('pme', 'mira_moves'), 'status': 'ACCEPTED', 'is_host': true, 'is_you': true},
            {..._card('p1', 'kevin_q'), 'status': 'INVITED', 'is_host': false, 'is_you': false},
          ],
        };
      }
      if (req.url.path == '/v1/parties/party7') return http.Response('{}', 500);
      return {
        'schema_version': 1,
        'friends': [
          {..._card('p1', 'kevin_q'), 'can_challenge': true},
        ],
        'incoming_requests': [],
        'outgoing_requests': [],
      };
    });
    await _pump(tester, const ChallengeLobbyScreen(), backend);

    await tester.tap(find.text('kevin_q'));
    await tester.pump();
    await tester.tap(find.text('Invite friends (1)'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    final post = backend.called('POST', '/v1/challenges').single;
    final body = jsonDecode(post.body) as Map;
    expect(body['friend_public_ids'], ['p1']);
    expect(body['question_language'], 'en');
    expect(find.text('Invited'), findsOneWidget);
    await tester.pumpWidget(const SizedBox()); // dispose the polling lobby
  });

  Json invites() => {
        'schema_version': 1,
        'invites': [
          {
            'invite_token': 'tok1', 'party_id': 'party3', 'question_language': 'en', 'mode': 'QUICK',
            'expires_at_ms': DateTime.now().millisecondsSinceEpoch + 40000,
            'host': {'public_id': 'p1', 'username': 'kevin_q', 'avatar_id': 'av_003', 'frame_id': 'frame_none'},
          },
        ],
      };

  testWidgets('incoming challenge accepts the host language and opens the lobby', (tester) async {
    final backend = _Backend((req) {
      if (req.url.path == '/v1/challenges/tok1/accept') {
        return {'schema_version': 1, 'party_id': 'party3', 'state': 'READY', 'match_id': null, 'members': []};
      }
      return invites();
    });
    await _pump(tester, const IncomingChallengeScreen(token: 'tok1'), backend);

    expect(find.text('kevin_q'), findsOneWidget);
    expect(find.text('English questions'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('challenge-accept')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    final post = backend.called('POST', '/v1/challenges/tok1/accept').single;
    expect((jsonDecode(post.body) as Map)['accept_question_language'], 'en');
    expect(find.text('LOBBY party3'), findsOneWidget);
  });

  testWidgets('incoming challenge shows a full lobby instead of joining', (tester) async {
    final backend = _Backend((req) {
      if (req.url.path == '/v1/challenges/tok1/accept') {
        return http.Response('{"error": {"code": "PARTY_FULL", "retryable": false}}', 409);
      }
      return invites();
    });
    await _pump(tester, const IncomingChallengeScreen(token: 'tok1'), backend);
    await tester.tap(find.byKey(const ValueKey('challenge-accept')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('This lobby is already full'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });
}
