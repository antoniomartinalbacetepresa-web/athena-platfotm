import 'dart:async';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/athena_auth_service.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class _MemoryTokenStore implements AuthTokenStore {
  String? token;

  @override
  Future<String?> readAccessToken() async => token;

  @override
  Future<void> writeAccessToken(String accessToken) async {
    token = accessToken;
  }

  @override
  Future<void> deleteAccessToken() async {
    token = null;
  }
}

AuthAccount _account(int id, String email) => AuthAccount(
      id: id,
      email: email,
      displayName: 'ATHENA user',
      isActive: true,
      createdAt: DateTime.parse('2026-09-21T08:00:00Z'),
      updatedAt: DateTime.parse('2026-09-21T08:00:00Z'),
    );

void main() {
  test('late rejection from owner A cannot revoke replacement owner B', () async {
    final store = _MemoryTokenStore();
    final session = AuthSession.forTesting(store);
    await session.establishPersisted(
      accessToken: 'owner-a.jwt',
      account: _account(7, 'owner-a@example.com'),
    );
    final pending = Completer<http.Response>();
    late http.Request captured;
    final service = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      session: session,
      client: MockClient((request) {
        captured = request;
        return pending.future;
      }),
    );

    final oldRequest = service.loadPositions();
    await Future<void>.delayed(Duration.zero);
    expect(captured.headers['Authorization'], 'Bearer owner-a.jwt');

    await session.establishPersisted(
      accessToken: 'owner-b.jwt',
      account: _account(23, 'owner-b@example.com'),
    );
    pending.complete(http.Response('{"detail":"old credential rejected"}', 401));

    await expectLater(oldRequest, throwsA(isA<AuthSessionRejectedException>()));
    expect(session.isAuthenticated, isTrue);
    expect(session.accessToken, 'owner-b.jwt');
    expect(session.account?.id, 23);
    expect(store.token, 'owner-b.jwt');
  });

  test('rejection of current credential still revokes durable authority', () async {
    final store = _MemoryTokenStore();
    final session = AuthSession.forTesting(store);
    await session.establishPersisted(
      accessToken: 'current.jwt',
      account: _account(7, 'current@example.com'),
    );
    final service = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      session: session,
      client: MockClient(
        (_) async => http.Response('{"detail":"credential rejected"}', 403),
      ),
    );

    await expectLater(
      service.loadPositions(),
      throwsA(
        isA<AuthSessionRejectedException>()
            .having((error) => error.statusCode, 'statusCode', 403),
      ),
    );
    expect(session.isAuthenticated, isFalse);
    expect(session.accessToken, isNull);
    expect(store.token, isNull);
  });
}
