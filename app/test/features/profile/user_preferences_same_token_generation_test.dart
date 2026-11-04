import 'dart:async';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
import 'package:app/features/profile/models/user_preferences.dart';
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

Future<void> _invoke(UserPreferencesService service, String operation) async {
  switch (operation) {
    case 'load':
      await service.load();
      return;
    case 'loadPersonalization':
      await service.loadPersonalization();
      return;
    case 'save':
      await service.save(const UserPreferences(
        riskTolerance: 'balanced',
        investmentHorizonYears: 15,
        baseCurrency: 'EUR',
        objective: 'long_term_growth',
      ));
      return;
    case 'delete':
      await service.delete();
      return;
    default:
      throw ArgumentError.value(operation);
  }
}

void main() {
  for (final operation in ['load', 'loadPersonalization', 'save', 'delete']) {
    test('$operation rejects an old successful response after same-token re-login',
        () async {
      final store = _MemoryTokenStore()..token = 'reused-token';
      final session = AuthSession.forTesting(store);
      session.establish(accessToken: 'reused-token', account: _account(1));
      final response = Completer<http.Response>();
      var requests = 0;
      final service = UserPreferencesService(
        baseUrl: 'https://athena.local',
        session: session,
        client: MockClient((request) {
          requests += 1;
          expect(request.headers['Authorization'], 'Bearer reused-token');
          return response.future;
        }),
      );

      final pending = _invoke(service, operation);
      await Future<void>.delayed(Duration.zero);
      expect(requests, 1);

      await session.clearPersisted();
      store.token = 'reused-token';
      session.establish(accessToken: 'reused-token', account: _account(2));

      response.complete(http.Response(
        operation == 'delete' ? '' : '{"status":"not_configured","data":null}',
        operation == 'delete' ? 204 : 200,
      ));
      await expectLater(
        pending,
        throwsA(isA<UserPreferencesAuthorityChangedException>()),
      );
      expect(session.isAuthenticated, isTrue);
      expect(session.account?.id, 2);
      expect(store.token, 'reused-token');
      service.dispose();
    });
  }

  test('late same-token 401 cannot revoke the replacement session', () async {
    final store = _MemoryTokenStore()..token = 'reused-token';
    final session = AuthSession.forTesting(store);
    session.establish(accessToken: 'reused-token', account: _account(1));
    final response = Completer<http.Response>();
    final service = UserPreferencesService(
      baseUrl: 'https://athena.local',
      session: session,
      client: MockClient((_) => response.future),
    );

    final pending = service.load();
    await Future<void>.delayed(Duration.zero);
    await session.clearPersisted();
    store.token = 'reused-token';
    session.establish(accessToken: 'reused-token', account: _account(2));

    response.complete(http.Response('{"detail":"old owner revoked"}', 401));
    await expectLater(
      pending,
      throwsA(isA<UserPreferencesSessionRejectedException>()),
    );
    expect(session.isAuthenticated, isTrue);
    expect(session.account?.id, 2);
    expect(session.accessToken, 'reused-token');
    expect(store.token, 'reused-token');

    await session.clearPersisted();
    await expectLater(service.load(), throwsStateError);
    service.dispose();
  });
}
