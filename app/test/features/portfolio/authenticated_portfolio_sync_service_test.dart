import 'dart:convert';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/portfolio/models/portfolio_position.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_service.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_sync_service.dart';
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

  PortfolioPosition localPosition({
    String symbol = 'AAPL',
    String exchange = 'NASDAQ',
    double shares = 3,
  }) =>
      PortfolioPosition(
        symbol: symbol,
        companyName: 'Sensitive Local Name',
        shares: shares,
        averagePrice: 123.45,
        currentPrice: 150.00,
        costBasisDate: DateTime.parse('2024-01-02T00:00:00Z'),
        priceCurrency: 'USD',
        exchange: exchange,
        currentPriceSourceProvider: 'market-provider',
      );

  test('sync transmits only declared identity and quantity', () async {
    session.establish(accessToken: 'signed.jwt.token', account: account());
    final putBodies = <Map<String, dynamic>>[];
    var getCount = 0;
    final client = MockClient((request) async {
      expect(request.headers['Authorization'], 'Bearer signed.jwt.token');
      if (request.method == 'GET') {
        getCount += 1;
        if (getCount == 1) {
          return http.Response(
            '{"data":{"positions":[],"positionCount":0}}',
            200,
          );
        }
        return http.Response(
          '{"data":{"positions":[{"id":9,"symbol":"AAPL","exchange":"NASDAQ","quantity":3.0,"createdAt":"2026-09-10T10:00:00Z","updatedAt":"2026-09-10T10:00:00Z"}],"positionCount":1}}',
          200,
        );
      }
      if (request.method == 'PUT') {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        putBodies.add(body);
        return http.Response(
          '{"data":{"id":9,"symbol":"AAPL","exchange":"NASDAQ","quantity":3.0,"createdAt":"2026-09-10T10:00:00Z","updatedAt":"2026-09-10T10:00:00Z"}}',
          200,
        );
      }
      return http.Response('{}', 500);
    });
    final remote = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      client: client,
      session: session,
    );
    final sync = AuthenticatedPortfolioSyncService(remoteService: remote);

    final report = await sync.syncDeclaredPositions([localPosition()]);

    expect(putBodies, hasLength(1));
    expect(putBodies.single, {
      'symbol': 'AAPL',
      'exchange': 'NASDAQ',
      'quantity': 3.0,
    });
    expect(putBodies.single.containsKey('averagePrice'), isFalse);
    expect(putBodies.single.containsKey('currentPrice'), isFalse);
    expect(putBodies.single.containsKey('costBasisDate'), isFalse);
    expect(putBodies.single.containsKey('capital'), isFalse);
    expect(putBodies.single.containsKey('ownerUserId'), isFalse);
    expect(putBodies.single.containsKey('userId'), isFalse);
    expect(report.localPositionCount, 1);
    expect(report.remotePositionCountBefore, 0);
    expect(report.upsertedPositionCount, 1);
    expect(report.remotePositionCountAfter, 1);
    expect(report.destructiveChangesApplied, isFalse);
    expect(report.sensitiveCostBasisTransmitted, isFalse);
  });

  test('sync rejects duplicate local listing identities before network', () async {
    session.establish(accessToken: 'signed.jwt.token', account: account());
    var called = false;
    final client = MockClient((request) async {
      called = true;
      return http.Response('{}', 500);
    });
    final remote = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      client: client,
      session: session,
    );
    final sync = AuthenticatedPortfolioSyncService(remoteService: remote);

    await expectLater(
      sync.syncDeclaredPositions([
        localPosition(symbol: 'aapl', exchange: 'nasdaq'),
        localPosition(symbol: ' AAPL ', exchange: ' NASDAQ '),
      ]),
      throwsStateError,
    );
    expect(called, isFalse);
  });

  test('sync rejects non-finite or non-positive quantities before network', () async {
    session.establish(accessToken: 'signed.jwt.token', account: account());
    var called = false;
    final client = MockClient((request) async {
      called = true;
      return http.Response('{}', 500);
    });
    final remote = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      client: client,
      session: session,
    );
    final sync = AuthenticatedPortfolioSyncService(remoteService: remote);

    await expectLater(
      sync.syncDeclaredPositions([localPosition(shares: 0)]),
      throwsArgumentError,
    );
    await expectLater(
      sync.syncDeclaredPositions([localPosition(shares: double.nan)]),
      throwsArgumentError,
    );
    expect(called, isFalse);
  });
}
