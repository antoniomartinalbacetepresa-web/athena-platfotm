import 'dart:convert';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  final session = AuthSession.instance;

  setUp(() => session.clear());
  tearDown(() => session.clear());

  AuthAccount account() => AuthAccount(
        id: 7,
        email: 'user@example.com',
        displayName: 'Athena User',
        isActive: true,
        createdAt: DateTime.parse('2026-09-10T10:00:00Z'),
        updatedAt: DateTime.parse('2026-09-10T10:00:00Z'),
      );

  test('guest session is rejected before any network call', () async {
    var called = false;
    final client = MockClient((request) async {
      called = true;
      return http.Response('{}', 500);
    });
    final service = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      client: client,
      session: session,
    );

    await expectLater(service.loadPositions(), throwsStateError);
    expect(called, isFalse);
  });

  test('load sends bearer token and parses only owner-visible positions', () async {
    session.establish(accessToken: 'signed.jwt.token', account: account());
    late http.Request captured;
    final client = MockClient((request) async {
      captured = request;
      return http.Response(
        '{"data":{"positions":[{"id":3,"symbol":"AAPL","exchange":"NASDAQ","quantity":4.5,"createdAt":"2026-09-10T10:00:00Z","updatedAt":"2026-09-10T10:01:00Z"}],"positionCount":1},"policy":{"ownerDerivedFromAuthenticatedToken":true}}',
        200,
      );
    });
    final service = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      client: client,
      session: session,
    );

    final positions = await service.loadPositions();

    expect(captured.method, 'GET');
    expect(captured.headers['Authorization'], 'Bearer signed.jwt.token');
    expect(positions, hasLength(1));
    expect(positions.single.id, 3);
    expect(positions.single.symbol, 'AAPL');
    expect(positions.single.quantity, 4.5);
  });

  test('upsert never sends owner identity supplied by the client', () async {
    session.establish(accessToken: 'signed.jwt.token', account: account());
    late http.Request captured;
    final client = MockClient((request) async {
      captured = request;
      return http.Response(
        '{"data":{"id":4,"symbol":"MSFT","exchange":"NASDAQ","quantity":2.0,"createdAt":"2026-09-10T10:00:00Z","updatedAt":"2026-09-10T10:00:00Z"}}',
        200,
      );
    });
    final service = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      client: client,
      session: session,
    );

    final position = await service.upsertPosition(
      symbol: ' msft ',
      exchange: ' nasdaq ',
      quantity: 2,
    );

    final body = jsonDecode(captured.body) as Map<String, dynamic>;
    expect(captured.method, 'PUT');
    expect(captured.headers['Authorization'], 'Bearer signed.jwt.token');
    expect(body['symbol'], 'MSFT');
    expect(body['exchange'], 'NASDAQ');
    expect(body['quantity'], 2.0);
    expect(body.containsKey('ownerUserId'), isFalse);
    expect(body.containsKey('userId'), isFalse);
    expect(position.id, 4);
  });

  test('delete uses bearer token and server position id', () async {
    session.establish(accessToken: 'signed.jwt.token', account: account());
    late http.Request captured;
    final client = MockClient((request) async {
      captured = request;
      return http.Response('', 204);
    });
    final service = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      client: client,
      session: session,
    );

    await service.deletePosition(11);

    expect(captured.method, 'DELETE');
    expect(captured.url.path, '/api/v1/user/portfolio/positions/11');
    expect(captured.headers['Authorization'], 'Bearer signed.jwt.token');
  });
}
