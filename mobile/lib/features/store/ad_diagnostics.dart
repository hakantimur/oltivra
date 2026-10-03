import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

/// Reports ad pipeline steps (UMP consent, ad loads) to `POST /v1/diagnostics/ads` so the server logs show why a
/// client requests no ads. Fire-and-forget; each distinct (stage, ok, code) is sent once per app run.
class AdDiagnostics {
  AdDiagnostics(this._ref);

  final Ref _ref;
  final _sent = <String>{};

  void report(String stage, {required bool ok, Object? code, String detail = ''}) {
    final codeText = code?.toString() ?? '';
    if (!_sent.add('$stage|$ok|$codeText')) return;
    unawaited(() async {
      try {
        await _ref.read(apiClientProvider).post('/v1/diagnostics/ads', {
          'stage': stage,
          'ok': ok,
          'code': codeText.length > 32 ? codeText.substring(0, 32) : codeText,
          'detail': detail.length > 200 ? detail.substring(0, 200) : detail,
        });
      } catch (_) {
        // Diagnostics never affect play.
      }
    }());
  }
}

final adDiagnosticsProvider = Provider<AdDiagnostics>((ref) => AdDiagnostics(ref));
