import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/api_client.dart';
import '../../core/providers.dart';
import '../../l10n/strings.dart';
import '../../router/routes.dart';

/// Social loads are user-driven (pull to refresh / retry button), so Riverpod's automatic retry is off.
Duration? _noRetry(int _, Object _) => null;

List<Json> jsonList(Object? value) =>
    ((value as List?) ?? const []).whereType<Map>().map((e) => e.cast<String, dynamic>()).toList();

/// `GET /v1/friends`: friends (with `can_challenge`), incoming and outgoing pending requests.
final friendsOverviewProvider = FutureProvider.autoDispose<Json>(
  (ref) => ref.read(apiClientProvider).get('/v1/friends'),
  retry: _noRetry,
);

/// `GET /v1/users/{public_id}`: another player's public profile plus the viewer's relationship.
final publicPlayerProvider = FutureProvider.autoDispose.family<Json, String>(
  (ref, publicId) => ref.read(apiClientProvider).get('/v1/users/$publicId'),
  retry: _noRetry,
);

/// Relationship values returned by `GET /v1/users/search` and `POST /v1/friends/requests`.
abstract final class Relationship {
  static const none = 'NONE';
  static const sent = 'REQUEST_SENT';
  static const received = 'REQUEST_RECEIVED';
  static const friend = 'FRIEND';
}

/// Opens the challenge composer, pre-selecting [publicId] when given (read back via `?friend=`).
void openChallenge(BuildContext context, {String? publicId}) =>
    context.push(publicId == null ? Routes.newChallenge : '${Routes.newChallenge}?friend=$publicId');

/// Display name for a question language code ("en" → "English").
String languageName(BuildContext context, String? code) {
  final key = 'social.language.$code';
  return Strings.has(key) ? context.t(key) : (code ?? '').toUpperCase();
}

/// `mm:ss` for countdowns derived from server `*_at_ms` deadlines.
String clockText(Duration d) {
  final s = d.isNegative ? 0 : d.inSeconds;
  return '${(s ~/ 60).toString().padLeft(2, '0')}:${(s % 60).toString().padLeft(2, '0')}';
}
