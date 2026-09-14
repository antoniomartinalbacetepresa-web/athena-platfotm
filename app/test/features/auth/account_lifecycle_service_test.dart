import 'dart:convert';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/account_lifecycle_service.dart';
import 'package:app/features/auth/services/athena_auth_account_closure.dart';
import 'package:app/features/auth/services/athena_auth_service.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
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

AuthAccount _account() => AuthAccount(
      id: 7,
      email: 'user@example.com',
      isActive: true,
      createdAt: DateTime.utc(2026, 9, 1),
      updatedAt: DateTime.utc(2026, 9, 1),
    );

Future<AuthSession> _authenticatedSession(_MemoryTokenStore store) async {
  final session = AuthSession.forTesting(store);
  await session.establishPersisted(
    accessToken: 'test-access-token',
    account: _account(),
  );
  return session;
}

void main() {
  test('successful account closure sends re-authentication and clears local token', () async {
    late http.Request captured;
    final client = MockClient((request) async {
      captured = request;
      return http.Response('', 204);
    });
    final store = _MemoryTokenStore();
    final session = await _authenticatedSession(store);
    final auth = AthenaAuthService(baseUrl: 'https://athena.local', client: client);
    final lifecycle = AccountLifecycleService(authService: auth, session: session);

    await lifecycle.closeCurrentAccount(currentPassword: 'test-current-passphrase');

    expect(captured.method, 'POST');
    expect(captured.url.path, '/api/v1/auth/close-account');
    expect(captured.headers['Authorization'], 'Bearer test-access-token');
    expect(captured.headers['Content-Type'], 'application/json');
    expect(
      (jsonDecode(captured.body) as Map<String, dynamic>)['currentPassword'],
      'test-current-passphrase',
    );
    expect(session.isAuthenticated, isFalse);
    expect(session.accessToken, isNull);
    expect(store.value, isNull);
  });

  test('failed re-authentication keeps current session and durable token', () async {
    final client = MockClient((request) async => http.Response('{}', 401));
    final store = _MemoryTokenStore();
    final session = await _authenticatedSession(store);
    final auth = AthenaAuthService(baseUrl: 'https://athena.local', client: client);
    final lifecycle = AccountLifecycleService(authService: auth, session: session);

    await expectLater(
      lifecycle.closeCurrentAccount(currentPassword: 'wrong-test-passphrase'),
      throwsA(isA<AccountClosureRejectedException>()),
    );

    expect(session.isAuthenticated, isTrue);
    expect(session.accessToken, 'test-access-token');
    expect(store.value, 'test-access-token');
  });

  test('closure validates password locally before any network call', () async {
    var called = false;
    final client = MockClient((request) async {
      called = true;
      return http.Response('', 204);
    });
    final store = _MemoryTokenStore();
    final session = await _authenticatedSession(store);
    final auth = AthenaAuthService(baseUrl: 'https://athena.local', client: client);
    final lifecycle = AccountLifecycleService(authService: auth, session: session);

    await expectLater(
      lifecycle.closeCurrentAccount(currentPassword: ''),
      throwsArgumentError,
    );

    expect(called, isFalse);
    expect(session.isAuthenticated, isTrue);
    expect(store.value, 'test-access-token');
  });
}
