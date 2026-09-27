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
import 'package:oltivra/auth/auth_service.dart';
import 'package:oltivra/core/providers.dart';
import 'package:oltivra/features/onboarding/age_gate_screen.dart';
import 'package:oltivra/features/onboarding/choose_name_screen.dart';
import 'package:oltivra/features/onboarding/game_guide_screen.dart';
import 'package:oltivra/features/onboarding/launch_screen.dart';
import 'package:oltivra/features/onboarding/pick_avatar_screen.dart';
import 'package:oltivra/features/onboarding/sign_in_screen.dart';
import 'package:oltivra/features/onboarding/terms_screen.dart';
import 'package:oltivra/router/routes.dart';
import 'package:oltivra/session/session.dart';
import 'package:oltivra/theme/app_theme.dart';
import 'package:oltivra/widgets/o_avatar.dart';
import 'package:oltivra/widgets/o_widgets.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _FakeAuth implements AuthService {
  _FakeAuth([this.current]);

  @override
  AuthUser? current;
  final calls = <String>[];
  Object? failWith;

  @override
  Stream<AuthUser?> get changes => const Stream.empty();

  Future<void> _record(String name) async {
    calls.add(name);
    if (failWith != null) throw failWith!;
  }

  @override
  Future<void> signInWithGoogle() => _record('google');

  @override
  Future<void> signInWithApple() => _record('apple');

  @override
  Future<void> signInWithEmail(String email, String password, {required bool create}) =>
      _record('email:$email:$create');

  @override
  Future<void> signOut() => _record('signOut');

  @override
  Future<void> reauthenticate() async {}

  @override
  Future<String?> idToken({bool forceRefresh = false}) async => current == null ? null : 'test:${current!.uid}';

  @override
  Future<String?> appCheckToken() async => null;
}

class _FixedSession extends SessionController {
  _FixedSession(this.value);

  final Session? value;

  @override
  Future<Session?> build() async => value;
}

const _user = AuthUser(uid: 'u1', provider: 'google');

Session _session({bool username = false, bool avatar = false, String? avatarId}) => Session({
      'account': {
        'exists': true,
        'onboarding': {'consent': true, 'username': username, 'avatar': avatar, 'rename_required': false},
      },
      'profile': {'username_display': username ? 'mira_moves' : null, 'avatar_id': avatarId},
      'legal': {'terms_version': '1', 'privacy_version': '1'},
    });

http.Response _json(Object body, [int status = 200]) =>
    http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});

Map<String, dynamic> _profile({String? username, String? avatarId}) => {
      'username_display': username,
      'avatar_id': avatarId,
      'onboarding': {'consent': true, 'username': username != null, 'avatar': avatarId != null, 'rename_required': false},
    };

class _Harness {
  _Harness(this.container, this.requests);

  final ProviderContainer container;
  final List<http.Request> requests;
}

/// Pumps [screen] under a GoRouter whose unknown routes render `route:<path>`, so navigation is observable.
Future<_Harness> _pump(
  WidgetTester tester,
  Widget screen, {
  AuthUser? user,
  Session? session,
  Map<String, Object> prefs = const {},
  FutureOr<http.Response> Function(http.Request request)? api,
  _FakeAuth? auth,
  List overrides = const [],
  SessionController Function()? sessionFactory,
  Size size = const Size(900, 2600),
  Locale? locale,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);

  SharedPreferences.setMockInitialValues(prefs);
  final sp = await SharedPreferences.getInstance();
  final fakeAuth = auth ?? _FakeAuth(user);
  final requests = <http.Request>[];
  final client = ApiClient(
    baseUrl: Uri.parse('http://api.test'),
    tokens: fakeAuth,
    client: MockClient((req) async {
      requests.add(req);
      if (api == null) return _json({'error': {'code': 'NOT_FOUND'}}, 404);
      return api(req);
    }),
  );
  final router = GoRouter(
    initialLocation: '/test',
    routes: [GoRoute(path: '/test', builder: (_, _) => screen)],
    errorBuilder: (_, state) => Scaffold(body: Text('route:${state.uri.path}')),
  );
  final container = ProviderContainer(retry: (_, _) => null, overrides: [
    sharedPrefsProvider.overrideWithValue(sp),
    authServiceProvider.overrideWithValue(fakeAuth),
    authStateProvider.overrideWithValue(AsyncValue.data(user)),
    apiClientProvider.overrideWithValue(client),
    sessionProvider.overrideWith(sessionFactory ?? () => _FixedSession(session)),
    ...overrides.cast(),
  ]);
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(
    container: container,
    child: MaterialApp.router(
      theme: buildTheme(),
      routerConfig: router,
      locale: locale,
      supportedLocales: const [Locale('en'), Locale('tr')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
    ),
  ));
  await tester.pumpAndSettle();
  return _Harness(container, requests);
}

OButton _button(WidgetTester tester, String key) => tester.widget<OButton>(find.byKey(Key(key)));

void main() {
  setUpAll(() => GoogleFonts.config.allowRuntimeFetching = false);

  group('LaunchScreen', () {
    testWidgets('signed out shows entry actions and starts at the age gate', (tester) async {
      await _pump(tester, const LaunchScreen());
      expect(find.text('Oltivra'), findsOneWidget);
      expect(find.text('Think fast. Rise higher.'), findsOneWidget);
      await tester.tap(find.text('Get started'));
      await tester.pumpAndSettle();
      expect(find.text('route:${Routes.ageGate}'), findsOneWidget);
    });

    testWidgets('bootstrap failure while signed in offers retry', (tester) async {
      await _pump(tester, const LaunchScreen(), user: _user, sessionFactory: _FailingSession.new);
      expect(find.byType(OErrorView), findsOneWidget);
      expect(find.text('Try again'), findsOneWidget);
    });
  });

  group('AgeGateScreen', () {
    testWidgets('confirming updates local onboarding state and moves to terms', (tester) async {
      final h = await _pump(tester, const AgeGateScreen());
      expect(_button(tester, 'age-continue').onPressed, isNull);

      await tester.tap(find.byKey(const Key('age-confirm')));
      await tester.pump();
      expect(_button(tester, 'age-continue').onPressed, isNotNull);

      await tester.tap(find.byKey(const Key('age-continue')));
      await tester.pumpAndSettle();
      expect(h.container.read(localOnboardingProvider).ageConfirmed, isTrue);
      expect(h.container.read(sharedPrefsProvider).getBool('onb.age'), isTrue);
      expect(find.text('route:${Routes.terms}'), findsOneWidget);
      expect(h.requests, isEmpty); // nothing leaves the device before sign-in
    });

    testWidgets('under 13 shows a blocking message without confirming', (tester) async {
      final h = await _pump(tester, const AgeGateScreen());
      await tester.tap(find.byKey(const Key('age-under-13')));
      await tester.pumpAndSettle();
      expect(find.text('Oltivra isn’t available yet'), findsOneWidget);
      expect(h.container.read(localOnboardingProvider).ageConfirmed, isFalse);
    });
  });

  group('TermsScreen', () {
    testWidgets('requires both Terms and Privacy before continuing', (tester) async {
      final h = await _pump(tester, const TermsScreen(), prefs: {'onb.age': true});
      expect(_button(tester, 'terms-continue').onPressed, isNull);

      await tester.tap(find.text('I agree to the Terms of Service.'));
      await tester.pump();
      expect(_button(tester, 'terms-continue').onPressed, isNull);

      await tester.tap(find.text('I agree to the Privacy Policy.'));
      await tester.pump();
      expect(_button(tester, 'terms-continue').onPressed, isNotNull);

      await tester.tap(find.byKey(const Key('terms-continue')));
      await tester.pumpAndSettle();
      expect(h.container.read(localOnboardingProvider).termsAccepted, isTrue);
      expect(find.text('route:${Routes.signIn}'), findsOneWidget);
    });

    testWidgets('document rows open the summary sheet', (tester) async {
      await _pump(tester, const TermsScreen());
      await tester.tap(find.text('Privacy Policy'));
      await tester.pumpAndSettle();
      expect(find.textContaining('We do not ask for your birthday'), findsOneWidget);
    });
  });

  group('SignInScreen', () {
    testWidgets('offers Google, Apple and email and ignores cancellation', (tester) async {
      final auth = _FakeAuth()..failWith = const AuthCancelled();
      await _pump(tester, const SignInScreen(), auth: auth);
      expect(find.text('Continue with Google'), findsOneWidget);
      expect(find.text('Continue with Apple'), findsOneWidget);
      expect(find.text('Continue with email'), findsOneWidget);
      expect(find.textContaining('ONLINE'), findsNothing);

      await tester.tap(find.byKey(const Key('signin-apple')));
      await tester.pumpAndSettle();
      expect(auth.calls, ['apple']);
      expect(find.byType(SnackBar), findsNothing);
    });

    testWidgets('email sheet validates and signs in', (tester) async {
      final auth = _FakeAuth();
      await _pump(tester, const SignInScreen(), auth: auth);
      await tester.tap(find.byKey(const Key('signin-email')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('email-submit')));
      await tester.pump();
      expect(find.text('Enter a valid email address.'), findsOneWidget);

      await tester.enterText(find.byKey(const Key('email-field')), 'mira@example.com');
      await tester.enterText(find.byKey(const Key('password-field')), 'secret123');
      await tester.tap(find.byKey(const Key('email-submit')));
      await tester.pumpAndSettle();
      expect(auth.calls, ['email:mira@example.com:true']);
    });
  });

  group('ChooseNameScreen', () {
    testWidgets('shows the taken error from the availability check', (tester) async {
      await _pump(tester, const ChooseNameScreen(), user: _user, session: _session(), api: (req) {
        expect(req.url.path, '/v1/usernames/availability');
        expect(req.url.queryParameters['username'], 'mira_moves');
        return _json({'schema_version': 1, 'available': false, 'reason': 'TAKEN'});
      });
      await tester.enterText(find.byKey(const Key('name-field')), 'mira_moves');
      await tester.pump(const Duration(milliseconds: 600));
      await tester.pumpAndSettle();
      expect(find.text('That name is already taken'), findsOneWidget);
      expect(_button(tester, 'name-continue').onPressed, isNull);
    });

    testWidgets('rejects bad characters locally without calling the API', (tester) async {
      final h = await _pump(tester, const ChooseNameScreen(), user: _user, session: _session());
      await tester.enterText(find.byKey(const Key('name-field')), 'mira-moves');
      await tester.pump(const Duration(milliseconds: 600));
      expect(find.text('Use 3–16 letters, numbers or _'), findsOneWidget);
      expect(h.requests, isEmpty);
    });

    testWidgets('maps USERNAME_TAKEN on submit inline and applies the profile on success', (tester) async {
      var claims = 0;
      final h = await _pump(tester, const ChooseNameScreen(), user: _user, session: _session(), api: (req) {
        if (req.method == 'GET') return _json({'available': true, 'reason': null});
        claims++;
        expect(req.url.path, '/v1/profile/username');
        final name = jsonDecode(req.body)['username'] as String;
        if (claims == 1) return _json({'error': {'code': 'USERNAME_TAKEN', 'retryable': false}}, 409);
        return _json({'schema_version': 1, 'profile': _profile(username: name)});
      });
      await tester.enterText(find.byKey(const Key('name-field')), 'mira_moves');
      await tester.pump(const Duration(milliseconds: 600));
      await tester.pumpAndSettle();
      expect(find.text('Name available'), findsOneWidget);

      await tester.tap(find.byKey(const Key('name-continue')));
      await tester.pumpAndSettle();
      expect(find.text('That name is already taken'), findsOneWidget);

      // Editing re-checks and the next claim succeeds.
      await tester.enterText(find.byKey(const Key('name-field')), 'mira_moves_2');
      await tester.pump(const Duration(milliseconds: 600));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('name-continue')));
      await tester.pumpAndSettle();
      final s = h.container.read(sessionProvider).value!;
      expect(s.usernameDone, isTrue);
      expect(s.username, 'mira_moves_2');
    });
  });

  group('PickAvatarScreen', () {
    final catalog = {
      'schema_version': 1,
      'avatars': [
        for (var i = 1; i <= 12; i++)
          {'id': 'av_${i.toString().padLeft(3, '0')}', 'motif': 'm$i', 'bg': '#FFFFFF', 'fg': '#000000',
            'accent': '#16B8A6', 'sort': 13 - i, 'active': i != 12},
      ],
    };

    testWidgets('renders the active catalog and saves the chosen avatar', (tester) async {
      final h = await _pump(tester, const PickAvatarScreen(), user: _user, session: _session(username: true),
          api: (req) {
        if (req.method == 'GET') {
          expect(req.url.path, '/v1/avatars');
          return _json(catalog);
        }
        expect(req.method, 'PATCH');
        expect(req.url.path, '/v1/profile/avatar');
        final id = jsonDecode(req.body)['avatar_id'] as String;
        return _json({'profile': _profile(username: 'mira_moves', avatarId: id)});
      });
      expect(find.byType(OAvatar), findsNWidgets(11)); // inactive entry hidden
      expect(find.byKey(const Key('avatar-av_012')), findsNothing);
      expect(_button(tester, 'avatar-save').onPressed, isNull);

      await tester.tap(find.byKey(const Key('avatar-av_003')));
      await tester.pump();
      await tester.tap(find.byKey(const Key('avatar-save')));
      await tester.pumpAndSettle();
      final s = h.container.read(sessionProvider).value!;
      expect(s.avatarId, 'av_003');
      expect(s.avatarDone, isTrue);
    });
  });

  group('small phone (tr)', _smallPhoneTurkish);

  group('GameGuideScreen', () {
    testWidgets('uses client-config numbers and marks the guide seen', (tester) async {
      final h = await _pump(tester, const GameGuideScreen(), user: _user, session: _session(username: true, avatar: true),
          overrides: [
            clientConfigProvider.overrideWithValue(const AsyncValue.data({
              'quick': {'questions': 12, 'seconds': 11, 'wrong_penalty': -5, 'no_answer_penalty': 0},
              'survival': {'seconds': 9},
              'survival_enabled': true,
            })),
          ]);
      expect(find.textContaining('12 questions'), findsOneWidget);
      expect(find.textContaining('costs 5 points'), findsOneWidget);
      expect(find.textContaining('9 seconds per question'), findsOneWidget);

      await tester.tap(find.byKey(const Key('guide-play')));
      await tester.pumpAndSettle();
      expect(h.container.read(localOnboardingProvider).guideSeen, isTrue);
      expect(find.text('route:${Routes.home}'), findsOneWidget);
    });
  });
}

void _smallPhoneTurkish() {
  final screens = <String, Widget>{
    'launch': const LaunchScreen(),
    'age': const AgeGateScreen(),
    'terms': const TermsScreen(),
    'signin': const SignInScreen(),
    'name': const ChooseNameScreen(),
    'avatar': const PickAvatarScreen(),
    'guide': const GameGuideScreen(),
  };
  for (final entry in screens.entries) {
    testWidgets('${entry.key} renders in Turkish on a small phone', (tester) async {
      await _pump(tester, entry.value, user: entry.key == 'launch' ? null : _user,
          session: _session(username: true), size: const Size(360, 740), locale: const Locale('tr'), api: (req) {
        if (req.url.path == '/v1/avatars') {
          return _json({'avatars': [for (var i = 1; i <= 12; i++) {'id': 'av_${i.toString().padLeft(3, '0')}', 'sort': i}]});
        }
        return _json({'quick': {'questions': 10}});
      });
      expect(tester.takeException(), isNull);
    });
  }
}

class _FailingSession extends SessionController {
  @override
  Future<Session?> build() async => throw ApiException(0, 'NETWORK_UNAVAILABLE', retryable: true);
}
