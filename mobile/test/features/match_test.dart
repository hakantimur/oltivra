import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:oltivra/features/store/interstitials.dart';
import 'package:oltivra/features/store/store_services.dart';
import 'package:oltivra/api/api_client.dart';
import 'package:oltivra/core/providers.dart';
import 'package:oltivra/features/match/match_screen.dart';
import 'package:oltivra/features/match/widgets/match_widgets.dart';
import 'package:oltivra/live/match_live_source.dart';
import 'package:oltivra/live/match_snapshot.dart';
import 'package:oltivra/session/session.dart';
import 'package:oltivra/theme/app_theme.dart';

const matchId = 'm1';

class _Tokens implements TokenSource {
  @override
  Future<String?> appCheckToken() async => null;

  @override
  Future<String?> idToken({bool forceRefresh = false}) async => 'test:u1';
}

class _NoInterstitials implements InterstitialAdGateway {
  int preloads = 0;

  @override
  void preload() => preloads++;

  @override
  Future<bool> showIfReady() async => false;
}

class _FixedSession extends SessionController {
  @override
  Future<Session?> build() async => Session({
        'features': {'rewarded_xp': true},
      });
}

int get _now => DateTime.now().millisecondsSinceEpoch;

Map<String, dynamic> _participant(String name, int slot, {int score = 0, String status = 'ACTIVE'}) => {
      'display_name': name,
      'avatar_id': 'av_00${slot + 1}',
      'frame_id': 'frame_none',
      'active': true,
      'left': false,
      'answer_locked': false,
      'score': score,
      'survival_status': status,
      'slot': slot,
    };

const _options = {'c1': 'Stratosphere', 'c2': 'Thermosphere', 'c3': 'Troposphere', 'c4': 'Mesosphere'};

Map<String, dynamic> _quickPublic(String state, {Map<String, dynamic> extra = const {}}) => {
      'mode': 'QUICK',
      'match_phase': 'QUICK_NORMAL',
      'state': state,
      'state_version': 12,
      'total_normal_rounds': 10,
      'round_id': 'r3',
      'round_number': 3,
      'round_kind': 'NORMAL',
      'difficulty': 'MEDIUM',
      'category_id': 'science_nature',
      'starts_at_ms': _now - 2000,
      'ends_at_ms': _now + 9000,
      'current_question': {
        'text': 'Which atmospheric layer contains the ozone layer?',
        'options': _options,
      },
      'participants': {
        'p1': _participant('mira_m', 0, score: 14),
        'p2': _participant('kevin_q', 1, score: 18),
        'p3': _participant('sora_7', 2, score: 9),
        'p4': _participant('elena_z', 3, score: 12),
      },
      'events': <Map<String, dynamic>>[],
      ...extra,
    };

const _order = {'A': 'c3', 'B': 'c1', 'C': 'c4', 'D': 'c2'};

MatchSnapshot _snap(Map<String, dynamic> public, Map<String, dynamic>? private, {String role = 'participant'}) =>
    MatchSnapshot(matchId: matchId, public: public, private: private, role: role, shardId: 's01');

class _Harness {
  final requests = <http.Request>[];
  Map<String, dynamic> Function(http.Request) respond = (_) => {'schema_version': 1, 'accepted': true};

  Future<void> pump(WidgetTester tester, MatchSnapshot? snapshot, {LiveHealth health = LiveHealth.connected}) async {
    GoogleFonts.config.allowRuntimeFetching = false;
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.7;
    addTearDown(tester.view.reset);
    final api = ApiClient(
      baseUrl: Uri.parse('http://api.test'),
      tokens: _Tokens(),
      client: MockClient((req) async {
        requests.add(req);
        return http.Response(jsonEncode(respond(req)), 200);
      }),
    );
    await tester.pumpWidget(ProviderScope(
      overrides: [
        apiClientProvider.overrideWithValue(api),
        matchLiveProvider(matchId).overrideWith((ref) => Stream.value(LiveUpdate(snapshot, health))),
        catalogProvider('reactions').overrideWith((ref) async => {
              'reactions': [
                {'id': 'text_gg', 'kind': 'TEXT', 'display': 'GG!', 'label': 'GG!'},
                {'id': 'emoji_fire', 'kind': 'EMOJI', 'display': '🔥', 'label': 'Fire'},
              ],
            }),
        clientConfigProvider.overrideWith((ref) async => {
              'quick': {'wrong_penalty': -4},
            }),
        sessionProvider.overrideWith(_FixedSession.new),
        interstitialAdGatewayProvider.overrideWithValue(_NoInterstitials()),
        adConsentProvider.overrideWith((ref) async => true),
      ],
      child: MaterialApp(theme: buildTheme(), home: const MatchScreen(matchId: matchId)),
    ));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }
}

AnswerOption _option(WidgetTester tester, String text) =>
    tester.widget<AnswerOption>(find.widgetWithText(AnswerOption, text));

void main() {
  testWidgets('quick active question renders four options in display order and submits the tapped concept',
      (tester) async {
    final h = _Harness()..respond = (_) => {'schema_version': 1, 'accepted': true, 'correct': true, 'score_delta': 7};
    await h.pump(
      tester,
      _snap(_quickPublic('ROUND_ACTIVE'), {
        'pid': 'p1',
        'round_id': 'r3',
        'eligible_to_answer': true,
        'option_order': _order,
        'own_answer_status': 'NOT_ANSWERED',
      }),
    );

    expect(find.text('Round 3 of 10'), findsOneWidget);
    expect(find.text('Which atmospheric layer contains the ozone layer?'), findsOneWidget);
    final texts = ['Troposphere', 'Stratosphere', 'Mesosphere', 'Thermosphere'];
    final ys = [for (final t in texts) tester.getTopLeft(find.text(t)).dy];
    expect(ys, orderedEquals([...ys]..sort()));
    expect(find.bySemanticsLabel(RegExp(r'^Option B, Stratosphere')), findsOneWidget);
    expect(find.textContaining('Wrong answer −4 pts'), findsOneWidget);

    await tester.tap(find.text('Stratosphere'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    final answers = h.requests.where((r) => r.url.path == '/v1/matches/$matchId/answer').toList();
    expect(answers, hasLength(1));
    final body = jsonDecode(answers.single.body) as Map;
    expect(body['option_id'], 'c1');
    expect(body['round_id'], 'r3');
    expect(body['request_id'], answers.single.headers['x-idempotency-key']);
    // Every other option is now disabled for this round.
    expect(_option(tester, 'Troposphere').onTap, isNull);
  });

  const imageQuestion = {
    'text': 'Which country uses this flag?',
    'options': _options,
    'signed_image_url': 'http://img.test/questions/g/v1/main.webp?exp=1',
    'image_aspect': 1.5,
  };

  Future<void> expectAllAnswersOnScreen(WidgetTester tester) async {
    expect(find.byType(Image), findsOneWidget);
    final screenHeight = tester.view.physicalSize.height / tester.view.devicePixelRatio;
    for (final t in ['Troposphere', 'Stratosphere', 'Mesosphere', 'Thermosphere']) {
      expect(tester.getBottomLeft(find.widgetWithText(AnswerOption, t)).dy, lessThanOrEqualTo(screenHeight), reason: t);
    }
  }

  testWidgets('image question keeps all four answers on screen while answering', (tester) async {
    await _Harness().pump(
      tester,
      _snap(_quickPublic('ROUND_ACTIVE', extra: {'current_question': imageQuestion}), {
        'pid': 'p1',
        'round_id': 'r3',
        'eligible_to_answer': true,
        'option_order': _order,
        'own_answer_status': 'NOT_ANSWERED',
      }),
    );
    await expectAllAnswersOnScreen(tester);
  });

  testWidgets('image question keeps all four answers on screen with the result banner', (tester) async {
    await _Harness().pump(
      tester,
      _snap(
        _quickPublic('ROUND_REVEAL', extra: {
          'current_question': imageQuestion,
          'correct_answer_reveal': {'concept_id': 'c1', 'text': 'Stratosphere', 'winner_pid': 'p2', 'points': 7},
        }),
        {
          'pid': 'p1',
          'round_id': 'r3',
          'eligible_to_answer': false,
          'option_order': _order,
          'own_answer_status': 'ANSWERED_WRONG',
          'selected_concept_id': 'c3',
          'score_delta': -4,
        },
      ),
    );
    expect(find.text('kevin_q wins +7'), findsOneWidget);
    await expectAllAnswersOnScreen(tester);
  });

  testWidgets('revealed state highlights the correct option and keeps the own wrong trace', (tester) async {
    final h = _Harness();
    await h.pump(
      tester,
      _snap(
        _quickPublic('ROUND_REVEAL', extra: {
          'correct_answer_reveal': {'concept_id': 'c1', 'text': 'Stratosphere', 'winner_pid': 'p2', 'points': 7},
        }),
        {
          'pid': 'p1',
          'round_id': 'r3',
          'eligible_to_answer': false,
          'own_answer_status': 'ANSWERED_WRONG',
          'selected_concept_id': 'c3',
          'score_delta': -4,
        },
      ),
    );

    expect(find.text('kevin_q wins +7'), findsOneWidget);
    expect(_option(tester, 'Stratosphere').look, OptionLook.correct);
    expect(_option(tester, 'Troposphere').look, OptionLook.wrong);
    expect(_option(tester, 'Mesosphere').look, OptionLook.dimmed);
    expect(_option(tester, 'Stratosphere').onTap, isNull);
  });

  testWidgets('survival eliminated player can choose to keep watching as a spectator', (tester) async {
    final h = _Harness();
    await h.pump(
      tester,
      _snap(
        {
          'mode': 'SURVIVAL',
          'match_phase': 'SURVIVAL_NORMAL',
          'state': 'ROUND_ACTIVE',
          'round_id': 'r6',
          'round_number': 6,
          'difficulty': 'HARD',
          'category_id': 'history',
          'starts_at_ms': _now - 1000,
          'ends_at_ms': _now + 9000,
          'active_count': 2,
          'current_question': {'text': 'Which city is carved from rose-red stone?', 'options': _options},
          'participants': {
            'p1': _participant('mira_m', 0, status: 'ELIMINATED', score: 4),
            'p2': _participant('kevin_q', 1),
            'p3': _participant('sora_7', 2),
          },
        },
        {'pid': 'p1', 'round_id': 'r6', 'eligible_to_answer': false, 'own_answer_status': 'INELIGIBLE'},
      ),
    );

    expect(find.text('You’re out this round.'), findsOneWidget);
    expect(find.text('Watch Battle'), findsOneWidget);

    await tester.tap(find.text('Watch Battle'));
    await tester.pump();

    expect(find.text('Which city is carved from rose-red stone?'), findsOneWidget);
    expect(find.text('You were eliminated · Watching only'), findsOneWidget);
    expect(_option(tester, 'Stratosphere').onTap, isNull);
  });

  testWidgets('final result lists standings with settled XP and rematch', (tester) async {
    final h = _Harness();
    await h.pump(
      tester,
      _snap(
        _quickPublic('FINISHED', extra: {
          'settlement_status': 'SETTLED',
          'rematch_until_ms': _now + 8000,
          'result_summary': {
            'standings': [
              {'pid': 'p1', 'place': 1, 'score': 52, 'wins': 4},
              {'pid': 'p2', 'place': 2, 'score': 25, 'wins': 3},
              {'pid': 'p4', 'place': 3, 'score': 12, 'wins': 2},
              {'pid': 'p3', 'place': 4, 'score': 9, 'wins': 1},
            ],
          },
        }),
        {
          'pid': 'p1',
          'settlement': {'place': 1, 'xp_awarded': 85, 'progress_ranked': false, 'progress_reward_offer': true},
        },
      ),
    );

    expect(find.text('1st Place — Victory'), findsOneWidget);
    expect(find.text('+85 XP'), findsOneWidget);
    expect(find.textContaining('Rematch ·'), findsOneWidget);
    final list = find.byType(Scrollable).first;
    await tester.scrollUntilVisible(find.text('Final standings'), 200, scrollable: list);
    for (final name in ['kevin_q', 'elena_z', 'sora_7']) {
      await tester.scrollUntilVisible(find.text(name), 200, scrollable: list);
      expect(find.text(name), findsOneWidget);
    }
    expect(find.text('25 pts'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('Play Again'), 200, scrollable: list);
    expect(find.text('Watch an ad for bonus XP'), findsOneWidget);
    expect(find.text('Play Again'), findsOneWidget);
  });

  testWidgets('reconnecting overlay keeps the last snapshot and blocks input', (tester) async {
    final h = _Harness();
    await h.pump(
      tester,
      _snap(_quickPublic('ROUND_ACTIVE'), {
        'pid': 'p1',
        'round_id': 'r3',
        'eligible_to_answer': true,
        'option_order': _order,
        'own_answer_status': 'NOT_ANSWERED',
      }),
      health: LiveHealth.reconnecting,
    );

    expect(find.text('Reconnecting to battle…'), findsOneWidget);
    expect(find.text('Which atmospheric layer contains the ozone layer?'), findsOneWidget);
    await tester.tap(find.text('Stratosphere'), warnIfMissed: false);
    await tester.pump();
    expect(h.requests.where((r) => r.url.path.endsWith('/answer')), isEmpty);
  });

  testWidgets('cancelled match shows the safely unavailable screen', (tester) async {
    final h = _Harness();
    await h.pump(tester, _snap(_quickPublic('CANCELLED'), {'pid': 'p1'}));
    expect(find.text('This battle couldn’t continue'), findsOneWidget);
    expect(find.text('Back to Home'), findsOneWidget);
  });
}
