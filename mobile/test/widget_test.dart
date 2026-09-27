import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:oltivra/api/api_client.dart';
import 'package:oltivra/auth/auth_service.dart';
import 'package:oltivra/core/providers.dart';
import 'package:oltivra/core/push.dart';
import 'package:oltivra/l10n/strings.dart';
import 'package:oltivra/live/match_snapshot.dart';
import 'package:oltivra/router/app_router.dart';
import 'package:oltivra/router/routes.dart';
import 'package:oltivra/session/session.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _Tokens implements TokenSource {
  int refreshes = 0;

  @override
  Future<String?> appCheckToken() async => null;

  @override
  Future<String?> idToken({bool forceRefresh = false}) async {
    if (forceRefresh) refreshes++;
    return 'test:u1';
  }
}

class _FixedSession extends SessionController {
  _FixedSession(this.value);

  final Session? value;

  @override
  Future<Session?> build() async => value;
}

void main() {
  group('Strings', () {
    test('falls back to English and fills placeholders', () {
      expect(Strings.lookup('tr', 'nav.home'), 'Ana Sayfa');
      expect(Strings.lookup('tr', 'level.short', {'level': 7}), 'Sv 7');
      expect(Strings.lookup('xx', 'nav.play'), 'Play');
      expect(Strings.lookup('en', 'missing.key'), 'missing.key');
    });
  });

  group('ApiClient', () {
    test('mutations send a UUIDv4 request id in body and idempotency header', () async {
      late http.Request seen;
      final client = ApiClient(
        baseUrl: Uri.parse('http://api.test'),
        tokens: _Tokens(),
        client: MockClient((req) async {
          seen = req;
          return http.Response('{"ok": true}', 200);
        }),
      );
      await client.post('/v1/profile/username', {'username': 'mira'});
      final body = jsonDecode(seen.body) as Map;
      expect(body['request_id'], seen.headers['x-idempotency-key']);
      expect(RegExp(r'^[0-9a-f-]{36}$').hasMatch(body['request_id'] as String), isTrue);
      expect(seen.headers['authorization'], 'Bearer test:u1');
    });

    test('maps the error envelope and refreshes the token once on UNAUTHENTICATED', () async {
      final tokens = _Tokens();
      var calls = 0;
      final client = ApiClient(
        baseUrl: Uri.parse('http://api.test'),
        tokens: tokens,
        client: MockClient((req) async {
          calls++;
          if (calls == 1) return http.Response('{"error": {"code": "UNAUTHENTICATED"}}', 401);
          return http.Response(
              '{"error": {"code": "USERNAME_TAKEN", "retryable": false, "detail": {"reason": "taken"}}}', 409);
        }),
      );
      await expectLater(
        client.post('/v1/profile/username', {'username': 'x'}),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'USERNAME_TAKEN').having((e) => e.reason, 'reason', 'taken')),
      );
      expect(tokens.refreshes, 1);
    });
  });

  group('MatchSnapshot', () {
    test('orders options by the viewer display order', () {
      final s = MatchSnapshot(matchId: 'm', public: {
        'state': 'ROUND_ACTIVE',
        'current_question': {
          'text': 'Q',
          'options': {'c1': 'One', 'c2': 'Two', 'c3': 'Three', 'c4': 'Four'},
        },
      }, private: {
        'pid': 'p1',
        'option_order': {'B': 'c1', 'A': 'c3', 'D': 'c2', 'C': 'c4'},
      });
      expect(s.orderedOptions.map((e) => '${e.key}${e.value}').toList(), ['Ac3', 'Bc1', 'Cc4', 'Dc2']);
      expect(s.isQuestionLive, isTrue);
    });
  });

  group('onboarding redirect', () {
    final probe = Provider.family<String?, String>((ref, location) => onboardingRedirect(ref, location));

    Future<ProviderContainer> container({AuthUser? user, Session? session, Map<String, Object> prefs = const {}}) async {
      SharedPreferences.setMockInitialValues(prefs);
      final sp = await SharedPreferences.getInstance();
      final c = ProviderContainer(overrides: [
        sharedPrefsProvider.overrideWithValue(sp),
        authStateProvider.overrideWithValue(AsyncValue.data(user)),
        sessionProvider.overrideWith(() => _FixedSession(session)),
      ]);
      addTearDown(c.dispose);
      await c.read(sessionProvider.future);
      return c;
    }

    Session session({bool consent = true, bool username = true, bool avatar = true}) => Session({
          'account': {
            'exists': true,
            'onboarding': {'consent': consent, 'username': username, 'avatar': avatar, 'rename_required': false},
          },
        });

    test('signed out walks age gate, terms, then sign in', () async {
      var c = await container();
      expect(c.read(probe(Routes.home)), Routes.ageGate);
      c = await container(prefs: {'onb.age': true});
      expect(c.read(probe(Routes.home)), Routes.terms);
      c = await container(prefs: {'onb.age': true, 'onb.terms': true});
      expect(c.read(probe(Routes.home)), Routes.signIn);
      expect(c.read(probe(Routes.launch)), isNull);
    });

    test('signed in requires name then avatar, then guide once', () async {
      const user = AuthUser(uid: 'u1', provider: 'google');
      var c = await container(user: user, session: session(username: false, avatar: false));
      expect(c.read(probe(Routes.home)), Routes.chooseName);
      c = await container(user: user, session: session(avatar: false));
      expect(c.read(probe(Routes.home)), Routes.pickAvatar);
      c = await container(user: user, session: session());
      expect(c.read(probe(Routes.signIn)), Routes.guide);
      expect(c.read(probe(Routes.home)), isNull);
      c = await container(user: user, session: session(), prefs: {'onb.guide': true});
      expect(c.read(probe(Routes.pickAvatar)), Routes.home);
    });
  });

  test('push payloads route to their screens', () {
    expect(routeForPush({'kind': 'FRIEND_CHALLENGE', 'invite_token': 'tok'}), Routes.incomingChallenge('tok'));
    expect(routeForPush({'kind': 'CHALLENGE_ACCEPTED', 'party_id': 'p1'}), Routes.challengeLobby('p1'));
    expect(routeForPush({'kind': 'LEAGUE_RESULT'}), Routes.league);
    expect(routeForPush({'kind': 'UNKNOWN'}), isNull);
  });
}
