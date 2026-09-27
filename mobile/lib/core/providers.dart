import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api/api_client.dart';
import '../auth/auth_service.dart';
import '../l10n/strings.dart';
import '../session/session.dart';
import 'env.dart';

/// Overridden in `main()` once SharedPreferences has loaded.
final sharedPrefsProvider = Provider<SharedPreferences>((ref) => throw UnimplementedError('sharedPrefsProvider'));

/// Overridden in `main()` with the Firebase implementation when `AUTH_MODE=firebase`.
final authServiceProvider = Provider<AuthService>((ref) => FakeAuthService(ref.watch(sharedPrefsProvider)));

final authStateProvider = StreamProvider<AuthUser?>((ref) async* {
  final auth = ref.watch(authServiceProvider);
  yield auth.current;
  yield* auth.changes;
});

final apiClientProvider = Provider<ApiClient>(
  (ref) => ApiClient(baseUrl: Uri.parse(Env.apiBaseUrl), tokens: ref.watch(authServiceProvider)),
);

// ------------------------------------------------------------------------------------------ locale

/// UI language (spec §8). `null` follows the device language when supported.
class LocaleController extends Notifier<Locale?> {
  static const _key = 'ui_language';

  @override
  Locale? build() {
    final saved = ref.watch(sharedPrefsProvider).getString(_key);
    return saved == null ? null : Locale(saved);
  }

  Future<void> set(String? language) async {
    final prefs = ref.read(sharedPrefsProvider);
    if (language == null) {
      await prefs.remove(_key);
      state = null;
    } else {
      await prefs.setString(_key, language);
      state = Locale(language);
    }
  }
}

final localeProvider = NotifierProvider<LocaleController, Locale?>(LocaleController.new);

// ------------------------------------------------------------------------------------------ local onboarding

/// Pre-sign-in onboarding answers (age gate, legal acceptance, guide seen). They are sent to
/// `POST /v1/onboarding/consent` right after sign-in; the server copy is authoritative afterwards.
class LocalOnboarding {
  const LocalOnboarding({this.ageConfirmed = false, this.termsAccepted = false, this.guideSeen = false});

  final bool ageConfirmed;
  final bool termsAccepted;
  final bool guideSeen;

  LocalOnboarding copyWith({bool? ageConfirmed, bool? termsAccepted, bool? guideSeen}) => LocalOnboarding(
        ageConfirmed: ageConfirmed ?? this.ageConfirmed,
        termsAccepted: termsAccepted ?? this.termsAccepted,
        guideSeen: guideSeen ?? this.guideSeen,
      );
}

class LocalOnboardingController extends Notifier<LocalOnboarding> {
  @override
  LocalOnboarding build() {
    final prefs = ref.watch(sharedPrefsProvider);
    return LocalOnboarding(
      ageConfirmed: prefs.getBool('onb.age') ?? false,
      termsAccepted: prefs.getBool('onb.terms') ?? false,
      guideSeen: prefs.getBool('onb.guide') ?? false,
    );
  }

  Future<void> confirmAge() async {
    await ref.read(sharedPrefsProvider).setBool('onb.age', true);
    state = state.copyWith(ageConfirmed: true);
  }

  Future<void> acceptTerms() async {
    await ref.read(sharedPrefsProvider).setBool('onb.terms', true);
    state = state.copyWith(termsAccepted: true);
  }

  Future<void> markGuideSeen() async {
    await ref.read(sharedPrefsProvider).setBool('onb.guide', true);
    state = state.copyWith(guideSeen: true);
  }
}

final localOnboardingProvider =
    NotifierProvider<LocalOnboardingController, LocalOnboarding>(LocalOnboardingController.new);

// ------------------------------------------------------------------------------------------ session

class SessionController extends AsyncNotifier<Session?> {
  @override
  Future<Session?> build() async {
    final user = await ref.watch(authStateProvider.future);
    if (user == null) return null;
    return _bootstrap();
  }

  Future<Session> _bootstrap() async {
    final api = ref.read(apiClientProvider);
    final raw = await api.post('/v1/session/bootstrap', {'client_time_ms': DateTime.now().millisecondsSinceEpoch});
    var session = Session(raw);
    ref.read(serverClockProvider).calibrate(session.serverTimeMs);
    final local = ref.read(localOnboardingProvider);
    if (!session.consentDone && local.ageConfirmed && local.termsAccepted) {
      final res = await api.post('/v1/onboarding/consent', {
        'age_gate_confirmed': true,
        'terms_version': session.legal['terms_version'] ?? '1',
        'privacy_version': session.legal['privacy_version'] ?? '1',
      });
      session = Session({
        ...raw,
        'profile': res['profile'],
        'account': {...(raw['account'] as Map), 'exists': true, 'onboarding': (res['profile'] as Map)['onboarding']},
      });
    }
    final ui = session.profile?['ui_language'] as String?;
    if (ui != null && ref.read(localeProvider) == null && supportedLanguages.contains(ui)) {
      unawaited(ref.read(localeProvider.notifier).set(ui));
    }
    return session;
  }

  Future<void> refresh() async {
    state = await AsyncValue.guard(_bootstrap);
  }

  /// Applies a profile returned by a mutation (`{"profile": {...}}`) without another bootstrap.
  void applyProfile(Json profile) {
    final current = state.value;
    if (current == null) return;
    final onboarding = profile['onboarding'];
    state = AsyncValue.data(Session({
      ...current.raw,
      'profile': profile,
      if (onboarding is Map) 'account': {...(current.raw['account'] as Map), 'exists': true, 'onboarding': onboarding},
    }));
  }
}

final sessionProvider = AsyncNotifierProvider<SessionController, Session?>(SessionController.new);

/// Non-authoritative server clock for countdown rendering only (spec §22.1).
class ServerClock {
  int _offsetMs = 0;

  void calibrate(int serverNowMs) => _offsetMs = serverNowMs - DateTime.now().millisecondsSinceEpoch;

  /// Blends a new observation in, favouring the smaller of the two (latency only ever adds delay).
  void observe(int serverNowMs) {
    final sample = serverNowMs - DateTime.now().millisecondsSinceEpoch;
    _offsetMs = ((_offsetMs * 3) + sample) ~/ 4;
  }

  int nowMs() => DateTime.now().millisecondsSinceEpoch + _offsetMs;
}

final serverClockProvider = Provider<ServerClock>((ref) => ServerClock());

final clientConfigProvider = FutureProvider<Json>((ref) async {
  final user = await ref.watch(authStateProvider.future);
  if (user == null) return const {};
  return ref.read(apiClientProvider).get('/v1/client-config');
});

/// Curated catalogs (`/v1/avatars`, `/v1/reactions`, `/v1/cosmetics`, `/v1/categories`), cached per session.
final catalogProvider = FutureProvider.family<Json, String>((ref, name) async {
  await ref.watch(authStateProvider.future);
  return ref.read(apiClientProvider).get('/v1/$name');
});
