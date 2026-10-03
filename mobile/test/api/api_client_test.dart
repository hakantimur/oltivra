import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:oltivra/api/api_client.dart';

class _NoTokens implements TokenSource {
  @override
  Future<String?> idToken({bool forceRefresh = false}) async => null;

  @override
  Future<String?> appCheckToken() async => null;
}

void main() {
  test('every request carries the client platform and build headers', () async {
    late http.BaseRequest seen;
    final api = ApiClient(
      baseUrl: Uri.parse('http://api.test'),
      tokens: _NoTokens(),
      client: MockClient((request) async {
        seen = request;
        return http.Response('{}', 200);
      }),
      clientHeaders: const {'x-client-platform': 'android', 'x-client-build': '9'},
    );

    await api.get('/v1/ping');

    expect(seen.headers['x-client-platform'], 'android');
    expect(seen.headers['x-client-build'], '9');
    expect(seen.headers['accept'], 'application/json');
  });
}
