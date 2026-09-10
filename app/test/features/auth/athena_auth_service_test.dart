import 'package:app/features/auth/services/athena_auth_service.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  tearDown(() => AuthSession.instance.clear());

  test('login uses OAuth form and validates bearer contract', () async {
    late http.Request captured;
    final client = MockClient((request) async {
      captured = request;
      return http.Response(
        '{"access_token":"signed.jwt.token","token_type":"bearer","expires_in":1800}',
        200,
        headers: {'content-type': 'application/json'},
      );
    });
    final service = AthenaAuthService(baseUrl: 'http://athena.local', client: client);

    final token = await service.login(
      email: ' user@example.com ',
      password: 'correct horse battery staple',
    );

    expect(token, 'signed.jwt.token');
    expect(captured.method, 'POST');
    expect(captured.url.path, '/api/v1/auth/token');
    expect(captured.headers['Content-Type'], 'application/x-www-form-urlencoded');
    expect(captured.bodyFields['username'], 'user@example.com');
    expect(captured.bodyFields['password'], 'correct horse battery staple');
  });

  test('getMe sends bearer token and parses account', () async {
    late http.Request captured;
    final client = MockClient((request) async {
      captured = request;
      return http.Response(
        '{"status":"authenticated","account":{"id":7,"email":"user@example.com","displayName":"Athena User","isActive":true,"createdAt":"2026-09-10T10:00:00Z","updatedAt":"2026-09-10T10:00:00Z"}}',
        200,
        headers: {'content-type': 'application/json'},
      );
    });
    final service = AthenaAuthService(baseUrl: 'http://athena.local', client: client);

    final account = await service.getMe('signed.jwt.token');

    expect(captured.method, 'GET');
    expect(captured.url.path, '/api/v1/auth/me');
    expect(captured.headers['Authorization'], 'Bearer signed.jwt.token');
    expect(account.id, 7);
    expect(account.email, 'user@example.com');
    expect(account.displayName, 'Athena User');
    expect(account.isActive, isTrue);
  });

  test('login rejects invalid token contract', () async {
    final client = MockClient((request) async => http.Response(
          '{"access_token":"token","token_type":"unexpected"}',
          200,
        ));
    final service = AthenaAuthService(baseUrl: 'http://athena.local', client: client);

    expect(
      service.login(email: 'user@example.com', password: 'password-password'),
      throwsFormatException,
    );
  });

  test('session never authenticates with token alone', () {
    expect(AuthSession.instance.isAuthenticated, isFalse);
    AuthSession.instance.clear();
    expect(AuthSession.instance.accessToken, isNull);
    expect(AuthSession.instance.account, isNull);
  });
}
