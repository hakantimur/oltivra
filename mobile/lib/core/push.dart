import 'dart:async';
import 'dart:io' show Platform;

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../router/app_router.dart';
import '../router/routes.dart';
import 'providers.dart';

/// Where a notification tap should land (payload keys from backend `NotificationService`, spec §34.2).
/// Only opaque tokens/ids travel in the payload; screens load everything else from the API.
String? routeForPush(Map<String, dynamic> data) {
  switch (data['kind']) {
    case 'FRIEND_REQUEST':
      return Routes.friendRequests;
    case 'FRIEND_CHALLENGE':
      final token = data['invite_token'];
      return token is String && token.isNotEmpty ? Routes.incomingChallenge(token) : Routes.social;
    case 'CHALLENGE_ACCEPTED':
      final party = data['party_id'];
      return party is String && party.isNotEmpty ? Routes.challengeLobby(party) : Routes.social;
    case 'LEADERBOARD_ENDING':
      return Routes.rankings;
    case 'MISSION_REMINDER':
      return Routes.missions;
    case 'LEAGUE_RESULT':
      return Routes.league;
  }
  return null;
}

/// Registers the FCM token with `POST /v1/devices` once the player is onboarded and routes notification taps.
/// Inactive without Firebase (fake-auth local development).
class PushService {
  PushService(this._ref);

  final Ref _ref;
  String? _registered;
  final _subs = <StreamSubscription<Object?>>[];

  Future<void> start() async {
    if (Firebase.apps.isEmpty) return;
    final messaging = FirebaseMessaging.instance;
    await messaging.requestPermission();
    _subs.add(FirebaseMessaging.onMessageOpenedApp.listen((m) => _open(m.data)));
    final initial = await messaging.getInitialMessage();
    if (initial != null) _open(initial.data);
    _subs.add(messaging.onTokenRefresh.listen(_register));
    final token = await messaging.getToken();
    if (token != null) await _register(token);
  }

  Future<void> _register(String token) async {
    if (token == _registered) return;
    try {
      await _ref.read(apiClientProvider).post('/v1/devices', {
        'token': token,
        'platform': Platform.isIOS ? 'ios' : 'android',
      });
      _registered = token;
    } catch (_) {
      // Best effort: retried on the next launch or token refresh.
    }
  }

  void _open(Map<String, dynamic> data) {
    final route = routeForPush(data);
    if (route != null) _ref.read(routerProvider).push(route);
  }

  void dispose() {
    for (final s in _subs) {
      s.cancel();
    }
  }
}

/// Starts push handling after onboarding completes; watched from the app root.
final pushServiceProvider = Provider<PushService?>((ref) {
  final onboarded = ref.watch(sessionProvider.select((s) => s.value?.onboarded == true));
  if (!onboarded) return null;
  final service = PushService(ref);
  ref.onDispose(service.dispose);
  unawaited(service.start().catchError((_) {}));
  return service;
});
