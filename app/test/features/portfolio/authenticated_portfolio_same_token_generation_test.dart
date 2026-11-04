import 'dart:async';
import 'dart:convert';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/athena_auth_service.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/repositories/market_repository.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_service.dart';
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

Future<void> _invoke(AuthenticatedPortfolioService service, String operation) async {
  switch (operation) {
    case 'load':
      await service.loadPositions();
      return;
    case 'history':
      await service.loadHistory();
      return;
    case 'upsert':
      await service.upsertPosition(symbol: 'AAPL', quantity: 1);
      return;
    case 'delete':
      await service.deletePosition(1);
      return;
    default:
      throw ArgumentError.value(operation);
  }
}

http.Response _holdings() => http.Response(
      jsonEncode({
        'data': {
          'positions': [
            {
              'id': 1,
              'symbol': 'AAPL',
              'exchange': 'NASDAQ',
              'quantity': 1.0,
              'averagePurchasePrice': 100.0,
              'createdAt': '2026-09-21T08:00:00Z',
              'updatedAt': '2026-09-21T08:00:00Z',
            }
          ]
        }
      }),
      200,
    );

class _PendingMarketRepository implements MarketRepository {
  _PendingMarketRepository(this.requested, this.pending);
  final Completer<void> requested;
  final Completer<MarketQuote> pending;

  @override
  Future<MarketQuote> getQuote(String symbol) {
    if (!requested.isCompleted) requested.complete();
    return pending.future;
  }
}

void main() {
  for (final operation in ['load', 'history', 'upsert', 'delete']) {
    test('$operation rejects a stale success after same-token owner replacement',
        () async {
      final store = _MemoryTokenStore()..token = 'reused-token';
      final session = AuthSession.forTesting(store);
      session.establish(accessToken: 'reused-token', account: _account(1));
      final requested = Completer<void>();
      final response = Completer<http.Response>();
      final service = AuthenticatedPortfolioService(
        baseUrl: 'https://athena.local',
        session: session,
        client: MockClient((request) {
          expect(request.headers['Authorization'], 'Bearer reused-token');
          if (!requested.isCompleted) requested.complete();
          return response.future;
        }),
      );

      final pending = _invoke(service, operation);
      await requested.future;
      await session.clearPersisted();
      store.token = 'reused-token';
      session.establish(accessToken: 'reused-token', account: _account(2));

      response.complete(http.Response(
        operation == 'delete' ? '' : '{}',
        operation == 'delete' ? 204 : 200,
      ));
      await expectLater(
        pending,
        throwsA(isA<AuthenticatedPortfolioAuthorityChangedException>()),
      );
      expect(session.isAuthenticated, isTrue);
      expect(session.account?.id, 2);
      expect(store.token, 'reused-token');
      service.dispose();
    });
  }

  test('late same-token 401 does not revoke the replacement owner', () async {
    final store = _MemoryTokenStore()..token = 'reused-token';
    final session = AuthSession.forTesting(store);
    session.establish(accessToken: 'reused-token', account: _account(1));
    final requested = Completer<void>();
    final response = Completer<http.Response>();
    final service = AuthenticatedPortfolioService(
      baseUrl: 'https://athena.local',
      session: session,
      client: MockClient((_) {
        if (!requested.isCompleted) requested.complete();
        return response.future;
      }),
    );

    final pending = service.loadPositions();
    await requested.future;
    await session.clearPersisted();
    store.token = 'reused-token';
    session.establish(accessToken: 'reused-token', account: _account(2));
    response.complete(http.Response('{"detail":"old session revoked"}', 401));

    await expectLater(pending, throwsA(isA<AuthSessionRejectedException>()));
    expect(session.isAuthenticated, isTrue);
    expect(session.account?.id, 2);
    expect(session.accessToken, 'reused-token');
    expect(store.token, 'reused-token');

    await session.clearPersisted();
    await expectLater(service.loadPositions(), throwsStateError);
    service.dispose();
  });

  test('same-token owner replacement during market quote aborts valuation',
      () async {
    final store = _MemoryTokenStore()..token = 'reused-token';
    final session = AuthSession.forTesting(store);
    session.establish(accessToken: 'reused-token', account: _account(1));
    final quoteRequested = Completer<void>();
    final quotePending = Completer<MarketQuote>();
    final service = AuthenticatedPortfolioService(
      baseUrl: 'https://athena.local',
      session: session,
      client: MockClient((_) async => _holdings()),
    );

    final valuation = service.loadValuedPositions(
      marketRepository: _PendingMarketRepository(quoteRequested, quotePending),
    );
    await quoteRequested.future;
    await session.clearPersisted();
    store.token = 'reused-token';
    session.establish(accessToken: 'reused-token', account: _account(2));
    quotePending.complete(MarketQuote(
      symbol: 'AAPL',
      companyName: 'Apple Inc.',
      currentPrice: 200,
      change: 1,
      changePercentage: 0.5,
      currency: 'USD',
      exchange: 'NASDAQ',
      updatedAt: DateTime.utc(2026, 9, 21, 9),
      sourceProvider: 'yahoo_finance',
      retrievedAt: DateTime.utc(2026, 9, 21, 9, 0, 2),
    ));

    await expectLater(
      valuation,
      throwsA(isA<AuthenticatedPortfolioAuthorityChangedException>()),
    );
    expect(session.account?.id, 2);
    service.dispose();
  });
}
