import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:oltivra/api/api_client.dart';
import 'package:oltivra/auth/auth_service.dart';
import 'package:oltivra/core/providers.dart';
import 'package:oltivra/features/progress/achievements_screen.dart';
import 'package:oltivra/features/progress/league_screen.dart';
import 'package:oltivra/features/progress/missions_screen.dart';
import 'package:oltivra/features/progress/my_profile_screen.dart';
import 'package:oltivra/features/progress/rankings_screen.dart';
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

Map<String, dynamic> _profile({String frameId = 'frame_none'}) => {
      'public_id': 'p_me',
      'username_display': 'mira_moves',
      'avatar_id': 'av_001',
      'frame_id': frameId,
      'featured_badge_ids': <String>[],
      'league': 'SILVER',
      'level': 12,
      'level_progress': {'level': 12, 'xp_into_level': 120, 'xp_for_level': 400},
      'quick_current_ranked_win_streak': 4,
      'quick_best_ranked_win_streak': 7,
      'survival_ranked_crowns_lifetime': 3,
      'matches_completed': 64,
      'badge_ids': ['badge_first_quick_win'],
      'frame_ids': ['frame_none', 'frame_crown'],
      'onboarding': {'consent': true, 'username': true, 'avatar': true, 'rename_required': false},
    };

Session _session() => Session({
      'account': {
        'exists': true,
        'onboarding': {'consent': true, 'username': true, 'avatar': true, 'rename_required': false},
      },
      'profile': _profile(),
    });

typedef _Handler = Future<Object?> Function(http.Request req);

class _Harness {
  final requests = <http.Request>[];
}

Future<_Harness> _pump(WidgetTester tester, Widget screen, _Handler handler) async {
  tester.view.physicalSize = const Size(900, 4000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  final harness = _Harness();
  final api = ApiClient(
    baseUrl: Uri.parse('http://api.test'),
    tokens: _Tokens(),
    client: MockClient((req) async {
      harness.requests.add(req);
      final body = await handler(req);
      if (body is http.Response) return body;
      return http.Response(jsonEncode(body ?? {}), 200, headers: {'content-type': 'application/json'});
    }),
  );
  await tester.pumpWidget(ProviderScope(
    overrides: [
      sharedPrefsProvider.overrideWithValue(prefs),
      authStateProvider.overrideWithValue(const AsyncValue.data(AuthUser(uid: 'u1', provider: 'google'))),
      sessionProvider.overrideWith(() => _FixedSession(_session())),
      apiClientProvider.overrideWithValue(api),
    ],
    child: MaterialApp(home: screen),
  ));
  await tester.pumpAndSettle();
  return harness;
}

void main() {
  setUpAll(() => GoogleFonts.config.allowRuntimeFetching = false);

  testWidgets('rankings opens on the league group with promotion and relegation zones', (tester) async {
    await _pump(tester, const RankingsScreen(), (req) async {
      if (req.url.path == '/v1/league') {
        Map<String, dynamic> row(int rank, String name, {bool me = false}) => {
              'rank': rank, 'public_id': 'p$rank', 'username': name, 'avatar_id': 'av_002', 'frame_id': 'frame_none',
              'weekly_xp': 1000 - rank * 10, 'me': me, 'zone': rank <= 2 ? 'PROMOTE' : rank > 8 ? 'DEMOTE' : null,
            };
        return {
          'league': 'SILVER', 'joined': true, 'rank': 3, 'group_size': 10, 'promote_count': 2, 'demote_count': 2,
          'ranked_weekly_xp': 970,
          'standings': [for (var i = 1; i <= 10; i++) row(i, i == 3 ? 'mira_moves' : 'rival_$i', me: i == 3)],
        };
      }
      return {};
    });

    expect(find.text('Promotion zone · top 2'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('Relegation zone · bottom 2'), 200);
    expect(find.text('Relegation zone · bottom 2'), findsOneWidget);
    await tester.scrollUntilVisible(find.byKey(const ValueKey('league.me')), -200);
    final mine = find.byKey(const ValueKey('league.me'));
    expect(find.descendant(of: mine, matching: find.text('mira_moves')), findsOneWidget);
  });

  testWidgets('rankings global tab renders the own row highlighted', (tester) async {
    await _pump(tester, const RankingsScreen(), (req) async {
      if (req.url.path == '/v1/league') return {'league': 'SILVER', 'joined': false, 'standings': []};
      if (req.url.path == '/v1/leaderboards/weekly') {
        Map<String, dynamic> e(int rank, String pid, String name, int xp) => {
              'rank': rank, 'public_id': pid, 'username': name, 'avatar_id': 'av_002', 'frame_id': 'frame_none',
              'league': 'SILVER', 'ranked_weekly_xp': xp, 'quick_ranked_wins': 3, 'survival_ranked_crowns': 0,
            };
        return {
          'week_id': '2026-W39',
          'entries': [e(1, 'p_a', 'elena_z', 1420), e(2, 'p_me', 'mira_moves', 860), e(3, 'p_b', 'tariq_9', 500)],
          'me': e(2, 'p_me', 'mira_moves', 860),
          'next_offset': null,
        };
      }
      return {};
    });

    await tester.tap(find.text('Global'));
    await tester.pumpAndSettle();
    expect(find.text('elena_z'), findsOneWidget);
    final mine = find.byKey(const ValueKey('progress.rankings.me'));
    expect(mine, findsOneWidget);
    expect(find.descendant(of: mine, matching: find.text('You')), findsOneWidget);
    expect(find.descendant(of: mine, matching: find.text('mira_moves')), findsOneWidget);
  });

  testWidgets('league screen shows the weekly rank, the rules and last week\'s promotion', (tester) async {
    await _pump(tester, const LeagueScreen(), (req) async {
      if (req.url.path == '/v1/league') {
        return {
          'league': 'GOLD', 'leagues': ['BRONZE', 'SILVER', 'GOLD'], 'joined': true, 'rank': 7, 'group_size': 100,
          'promote_count': 20, 'demote_count': 20, 'ranked_weekly_xp': 640,
          'week_ends_at_ms': DateTime.now().millisecondsSinceEpoch + 86400000,
          'last_result': {'week_id': '2026-W38', 'rank': 4, 'from': 'SILVER', 'to': 'GOLD', 'outcome': 'PROMOTED'},
          'standings': [],
        };
      }
      return {};
    });
    expect(find.text('Last week you finished #4 and moved up to Gold!'), findsOneWidget);
    expect(find.text('#7 of 100 · 640 XP this week'), findsOneWidget);
    expect(find.text('You’re in the promotion zone — keep it up!'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('The bottom 20 move down a league.'), 200);
    expect(find.text('The top 20 move up a league when the week ends.'), findsOneWidget);
  });

  testWidgets('missions claim calls the claim endpoint', (tester) async {
    var claimed = false;
    final harness = await _pump(tester, const MissionsScreen(), (req) async {
      switch (req.url.path) {
        case '/v1/missions/daily':
          return {
            'period': 'DAILY', 'period_id': 'D2026-09-27', 'ends_at_ms': DateTime.now().millisecondsSinceEpoch + 3600000,
            'missions': [
              {'mission_id': 'D2026-09-27.0', 'template_id': 'play_quick_3', 'target': 3, 'progress': 3,
                'completed': true, 'claimed': claimed, 'xp': 40},
              {'mission_id': 'D2026-09-27.1', 'template_id': 'answer_correct_10', 'target': 10, 'progress': 7,
                'completed': false, 'claimed': false, 'xp': 30},
            ],
          };
        case '/v1/missions/weekly':
          return {'period': 'WEEKLY', 'period_id': 'W2026-W39', 'ends_at_ms': 0, 'missions': []};
        case '/v1/missions/D2026-09-27.0/claim':
          claimed = true;
          return {'mission_id': 'D2026-09-27.0', 'claimed': true, 'xp_awarded': 40, 'total_xp': 1000};
        case '/v1/profile':
          return {'profile': _profile()};
      }
      return {};
    });

    expect(find.text('Play 3 Quick Battles'), findsOneWidget);
    await tester.tap(find.text('Claim +40 XP'));
    await tester.pumpAndSettle();

    final claim = harness.requests.where((r) => r.url.path == '/v1/missions/D2026-09-27.0/claim').toList();
    expect(claim, hasLength(1));
    expect(claim.single.method, 'POST');
    expect(claim.single.headers['x-idempotency-key'], isNotNull);
    expect(find.text('Claim +40 XP'), findsNothing);
    expect(find.text('Claimed'), findsOneWidget);
  });

  testWidgets('achievements equip frame patches cosmetics', (tester) async {
    final harness = await _pump(tester, const AchievementsScreen(), (req) async {
      switch (req.url.path) {
        case '/v1/cosmetics':
          return {
            'frames': [
              {'id': 'frame_none', 'kind': 'DEFAULT', 'color': null, 'names': {'en': 'No frame', 'tr': 'Çerçeve yok'}},
              {'id': 'frame_crown', 'kind': 'ACHIEVEMENT', 'color': '#FFC94A', 'names': {'en': 'Crowned', 'tr': 'Taçlı'}},
              {'id': 'frame_legend', 'kind': 'LEAGUE', 'color': '#AF2759', 'names': {'en': 'Legend League', 'tr': 'Efsane Lig'}},
            ],
            'badges': [
              {'id': 'badge_first_quick_win', 'names': {'en': 'First Quick Win', 'tr': 'İlk Hızlı Zafer'}, 'icon': 'bolt'},
              {'id': 'badge_10_crowns', 'names': {'en': '10 Survival Crowns', 'tr': '10 Taç'}, 'icon': 'crown'},
            ],
          };
        case '/v1/profile/cosmetics':
          return {'profile': _profile(frameId: 'frame_crown')};
      }
      return {};
    });

    expect(find.text('Crowned'), findsOneWidget);
    expect(find.byKey(const ValueKey('progress.equip.frame_legend')), findsNothing); // not owned
    await tester.tap(find.byKey(const ValueKey('progress.equip.frame_crown')));
    await tester.pumpAndSettle();

    final patch = harness.requests.singleWhere((r) => r.url.path == '/v1/profile/cosmetics');
    expect(patch.method, 'PATCH');
    expect((jsonDecode(patch.body) as Map)['frame_id'], 'frame_crown');
    // The session now carries the equipped frame, so the crown card no longer offers "Equip".
    expect(find.byKey(const ValueKey('progress.equip.frame_crown')), findsNothing);
    expect(find.byKey(const ValueKey('progress.equip.frame_none')), findsOneWidget);
  });

  testWidgets('profile shows level, stats and recent matches', (tester) async {
    await _pump(tester, const MyProfileScreen(), (req) async {
      switch (req.url.path) {
        case '/v1/match-history':
          return {
            'matches': [
              {'match_id': 'm1', 'mode': 'QUICK', 'completed_at_ms': DateTime.now().millisecondsSinceEpoch - 7200000,
                'cancelled': false, 'ranked': true, 'place': 1, 'score': 820, 'xp_awarded': 55, 'players': 4},
            ],
          };
        case '/v1/category-stats':
          return {'categories': [
            {'category_id': 'music', 'answered': 10, 'correct': 7, 'accuracy': 0.7},
          ]};
        case '/v1/cosmetics':
          return {'frames': [], 'badges': []};
      }
      return {};
    });

    expect(find.text('mira_moves'), findsOneWidget);
    expect(find.text('LVL 12'), findsOneWidget);
    expect(find.text('120 / 400 XP'), findsOneWidget);
    expect(find.text('7'), findsOneWidget); // best streak
    expect(find.text('70% overall accuracy'), findsOneWidget);
    expect(find.text('#1 of 4'), findsOneWidget);
  });
}

