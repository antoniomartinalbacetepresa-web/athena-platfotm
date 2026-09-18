import 'package:app/core/routing/app_routes.dart';
import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/presentation/pages/register_page.dart';
import 'package:app/features/auth/services/athena_auth_service.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class _MemoryTokenStore implements AuthTokenStore {
  String? value;
  @override
  Future<void> deleteAccessToken() async => value = null;
  @override
  Future<String?> readAccessToken() async => value;
  @override
  Future<void> writeAccessToken(String token) async => value = token;
}

void main() {
  testWidgets('registered account session survives through durable token storage', (tester) async {
    final store = _MemoryTokenStore();
    final session = AuthSession.forTesting(store);
    final client = MockClient((request) async {
      if (request.url.path.endsWith('/register')) {
        return http.Response(
          '{"status":"account_created","account":{"id":7,"email":"user@example.com","isActive":true,"createdAt":"2026-09-18T10:00:00Z","updatedAt":"2026-09-18T10:00:00Z"}}',
          201,
        );
      }
      if (request.url.path.endsWith('/token')) {
        return http.Response('{"access_token":"registered.jwt","token_type":"bearer"}', 200);
      }
      if (request.url.path.endsWith('/me')) {
        return http.Response(
          '{"status":"authenticated","account":{"id":7,"email":"user@example.com","isActive":true,"createdAt":"2026-09-18T10:00:00Z","updatedAt":"2026-09-18T10:00:00Z"}}',
          200,
        );
      }
      return http.Response('', 404);
    });

    final auth = AthenaAuthService(baseUrl: 'https://athena.local', client: client);
    final account = await auth.register(email: 'user@example.com', password: 'replacement-password');
    final token = await auth.login(email: account.email, password: 'replacement-password');
    final verified = await auth.getMe(token);
    await session.establishPersisted(accessToken: token, account: verified);

    expect(session.isAuthenticated, isTrue);
    expect(session.account?.id, 7);
    expect(store.value, 'registered.jwt');

    final restored = AuthSession.forTesting(store);
    final outcome = await restored.restorePersisted(
      validateToken: auth.getMe,
    );
    expect(outcome, AuthSessionRestoreOutcome.authenticated);
    expect(restored.isAuthenticated, isTrue);
    expect(restored.account?.email, 'user@example.com');
    expect(restored.accessToken, 'registered.jwt');
  });
}
