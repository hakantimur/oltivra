import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:uuid/uuid.dart';

/// Error envelope from the backend (spec §19.2): `{"error": {"code", "message_key", "retryable", "detail"}}`.
class ApiException implements Exception {
  ApiException(this.status, this.code, {this.detail = const {}, this.retryable = false, this.retryAfter});

  final int status;
  final String code;
  final Map<String, dynamic> detail;
  final bool retryable;
  final Duration? retryAfter;

  String? get reason => detail['reason'] as String?;
  bool get isNetwork => status == 0;

  @override
  String toString() => 'ApiException($status, $code, $detail)';
}

/// Supplies a fresh Firebase ID token (and optionally an App Check token) for each request.
abstract interface class TokenSource {
  Future<String?> idToken({bool forceRefresh = false});
  Future<String?> appCheckToken();
}

typedef Json = Map<String, dynamic>;

class ApiClient {
  ApiClient({
    required this.baseUrl,
    required this.tokens,
    http.Client? client,
    this.timeout = const Duration(seconds: 12),
    this.clientHeaders = const {},
  }) : _http = client ?? http.Client();

  final Uri baseUrl;
  final TokenSource tokens;
  final Duration timeout;

  /// Sent with every request (`x-client-platform`, `x-client-build`) so server logs can tell app builds apart.
  final Map<String, String> clientHeaders;
  final http.Client _http;
  static const _uuid = Uuid();

  static String newRequestId() => _uuid.v4();

  Future<Json> get(String path, {Map<String, String>? query}) => _send('GET', path, query: query);

  /// Mutations always carry a UUIDv4 request_id (body) and the same x-idempotency-key header so that a
  /// retried request replays the original response instead of applying twice (spec §19.1).
  Future<Json> post(String path, [Json body = const {}, String? requestId]) =>
      _send('POST', path, body: body, requestId: requestId ?? newRequestId());

  Future<Json> patch(String path, [Json body = const {}]) =>
      _send('PATCH', path, body: body, requestId: newRequestId());

  Future<Json> put(String path, [Json body = const {}]) => _send('PUT', path, body: body, requestId: newRequestId());

  Future<Json> delete(String path, [Json body = const {}]) =>
      _send('DELETE', path, body: body, requestId: newRequestId());

  Future<Json> _send(String method, String path,
      {Json? body, String? requestId, Map<String, String>? query, bool retriedAuth = false}) async {
    final uri = baseUrl.replace(path: '${baseUrl.path}$path', queryParameters: query);
    final headers = <String, String>{'accept': 'application/json', ...clientHeaders};
    final token = await tokens.idToken(forceRefresh: retriedAuth);
    if (token != null) headers['authorization'] = 'Bearer $token';
    final appCheck = await tokens.appCheckToken();
    if (appCheck != null) headers['x-firebase-appcheck'] = appCheck;
    String? encoded;
    if (body != null) {
      headers['content-type'] = 'application/json';
      if (requestId != null) headers['x-idempotency-key'] = requestId;
      encoded = jsonEncode({...body, 'request_id': ?requestId});
    }
    final request = http.Request(method, uri)..headers.addAll(headers);
    if (encoded != null) request.body = encoded;
    http.Response response;
    try {
      response = await http.Response.fromStream(await _http.send(request).timeout(timeout));
    } on TimeoutException {
      throw ApiException(0, 'NETWORK_TIMEOUT', retryable: true);
    } catch (_) {
      throw ApiException(0, 'NETWORK_UNAVAILABLE', retryable: true);
    }
    final decoded = response.body.isEmpty ? <String, dynamic>{} : jsonDecode(utf8.decode(response.bodyBytes));
    if (response.statusCode >= 200 && response.statusCode < 300) {
      return decoded is Map<String, dynamic> ? decoded : {'data': decoded};
    }
    final error = (decoded is Map<String, dynamic> ? decoded['error'] : null) as Map<String, dynamic>? ?? {};
    final code = error['code'] as String? ?? 'HTTP_${response.statusCode}';
    if (code == 'UNAUTHENTICATED' && !retriedAuth && (error['detail'] as Map?)?['reason'] == null) {
      // An expired ID token: refresh once and replay with the same idempotency key.
      return _send(method, path, body: body, requestId: requestId, query: query, retriedAuth: true);
    }
    final retryAfter = int.tryParse(response.headers['retry-after'] ?? '');
    throw ApiException(
      response.statusCode,
      code,
      detail: (error['detail'] as Map?)?.cast<String, dynamic>() ?? const {},
      retryable: error['retryable'] as bool? ?? false,
      retryAfter: retryAfter == null ? null : Duration(seconds: retryAfter),
    );
  }
}
