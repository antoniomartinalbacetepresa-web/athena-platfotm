import 'dart:async';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/account_lifecycle_service.dart';
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

AuthAccount _account(int id) => AuthAccount(
      id: id,
      email: 'owner-$id@example.com',
      isActive: true,
      createdAt: DateTime.utc(2026, 9, 21),
      updatedAt: DateTime.utc(2026, 9, 21),
    );

Future<AuthSession> _session(_MemoryTokenStore store) async {
  final session = AuthSession.forTesting(store);
  await session.establishPersisted(
    accessToken: 'old-token',
    account: _account(1),
  );
  return session;
}

Future<void> _replaceAuthority(AuthSession session) async {
  await session.establishPersisted(
    accessToken: 'replacement-token',
    account: _account(2),
  );
}

void main() {
  test('late logout response cannot clear a replacement authenticated session', () async {
    final gate = Completer<void>();
    final requestStarted = Completer<void>();
    final store = _MemoryTokenStore();
    final session = await _session(store);
    final auth = AthenaAuthService(
      baseUrl: 'https://athena.local',
      client: MockClient((request) async {
        expect(request.url.path, '/api/v1/auth/logout');
        expect(request.headers['Authorization'], 'Bearer old-token');
        requestStarted.complete();
        await gate.future;
        return http.Response('', 204);
      }),
    );
    final lifecycle = AccountLifecycleService(authService: auth, session: session);

    final pending = lifecycle.logoutCurrentSession();
    await requestStarted.future;
    await _replaceAuthority(session);
    gate.complete();
    final result = await pending;

    expect(result.localCredentialDeleted, isFalse);
    expect(session.isAuthenticated, isTrue);
    expect(session.accessToken, 'replacement-token');
    expect(session.account?.id, 2);
    expect(store.value, 'replacement-token');
  });

  test('late password-change response cannot clear a replacement session', () async {
    final gate = Completer<void>();
    final requestStarted = Completer<void>();
    final store = _MemoryTokenStore();
    final session = await _session(store);
    final auth = AthenaAuthService(
      baseUrl: 'https://athena.local',
      client: MockClient((request) async {
        expect(request.url.path, '/api/v1/auth/change-password');
        expect(request.headers['Authorization'], 'Bearer old-token');
        requestStarted.complete();
        await gate.future;
        return http.Response('', 204);
      }),
    );
    final lifecycle = AccountLifecycleService(authService: auth, session: session);

    final pending = lifecycle.changeCurrentPassword(
      currentPassword: 'current-password',
      newPassword: 'replacement-password',
    );
    await requestStarted.future;
    await _replaceAuthority(session);
    gate.complete();
    final result = await pending;

    expect(result.localCredentialDeleted, isFalse);
    expect(session.isAuthenticated, isTrue);
    expect(session.accessToken, 'replacement-token');
    expect(store.value, 'replacement-token');
  });

  test('late account-closure response cannot clear a different owner session', () async {
    final gate = Completer<void>();
    final requestStarted = Completer<void>();
    final store = _MemoryTokenStore();
    final session = await _session(store);
    final auth = AthenaAuthService(
      baseUrl: 'https://athena.local',
      client: MockClient((request) async {
        expect(request.url.path, '/api/v1/auth/close-account');
        expect(request.headers['Authorization'], 'Bearer old-token');
        requestStarted.complete();
        await gate.future;
        return http.Response('', 204);
      }),
    );
    final lifecycle = AccountLifecycleService(authService: auth, session: session);

    final pending = lifecycle.closeCurrentAccount(
      currentPassword: 'current-password',
    );
    await requestStarted.future;
    await _replaceAuthority(session);
    gate.complete();
    final result = await pending;

    expect(result.localCredentialDeleted, isFalse);
    expect(session.isAuthenticated, isTrue);
    expect(session.accessToken, 'replacement-token');
    expect(session.account?.id, 2);
    expect(store.value, 'replacement-token');
  });
}