import 'dart:async';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
import 'package:app/features/profile/services/user_preferences_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class _MemoryTokenStore implements AuthTokenStore {
  String? token;

  @override
  Future<void> deleteAccessToken() async => token = null;

  @override
  Future<String?> readAccessToken() async => token;

  @override
  Future<void> writeAccessToken(String value) async => token = value;
}

AuthAccount _account(int id) => AuthAccount(
      id: id,
      email: 'owner-$id@example.com',
      displayName: 'Owner $id',
      isActive: true,
      createdAt: DateTime.utc(2026, 9, 21),
      updatedAt: DateTime.utc(2026, 9, 21),
    );

void main() {
  test('late Profile 401 cannot revoke a replacement authenticated owner', () async {
    final store = _MemoryTokenStore()..token = 'owner-a-token';
    final session = AuthSession.forTesting(store);
    session.establish(accessToken: 'owner-a-token', account: _account(1));
    final response = Completer<http.Response>();
    final service = UserPreferencesService(
      baseUrl: 'https://athena.local',
      session: session,
      client: MockClient((request) async {
        expect(request.headers['Authorization'], 'Bearer owner-a-token');
        return response.future;
      }),
    );

    final pending = service.load();
    await Future<void>.delayed(Duration.zero);

    store.token = 'owner-b-token';
    session.establish(accessToken: 'owner-b-token', account: _account(2));
    response.complete(http.Response('{"detail":"expired owner A"}', 401));

    await expectLater(
      pending,
      throwsA(isA<UserPreferencesSessionRejectedException>()),
    );
    expect(session.isAuthenticated, isTrue);
    expect(session.accessToken, 'owner-b-token');
    expect(session.account?.id, 2);
    expect(store.token, 'owner-b-token');

    service.dispose();
  });

  test('Profile 403 still revokes the same credential that made the request', () async {
    final store = _MemoryTokenStore()..token = 'owner-token';
    final session = AuthSession.forTesting(store);
    session.establish(accessToken: 'owner-token', account: _account(7));
    final service = UserPreferencesService(
      baseUrl: 'https://athena.local',
      session: session,
      client: MockClient((_) async => http.Response('{}', 403)),
    );

    await expectLater(
      service.load(),
      throwsA(isA<UserPreferencesSessionRejectedException>()),
    );
    expect(session.isAuthenticated, isFalse);
    expect(session.accessToken, isNull);
    expect(store.token, isNull);

    service.dispose();
  });
}