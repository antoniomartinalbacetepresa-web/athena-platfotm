import 'dart:convert';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/athena_auth_service.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/repositories/market_repository.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class _MarketRepository implements MarketRepository {
  _MarketRepository(this.quote);

  final MarketQuote quote;
  final requestedSymbols = <String>[];

  @override
  Future<MarketQuote> getQuote(String symbol) async {
    requestedSymbols.add(symbol);
    return quote;
  }
}

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

  MarketQuote quote({
    String symbol = 'AAPL',
    String? exchange = 'NASDAQ',
    String? provider = 'yahoo_finance',
    double price = 200,
    DateTime? observedAt,
    DateTime? retrievedAt,
  }) {
    final observed = observedAt ?? DateTime.parse('2026-09-15T16:00:00Z');
    return MarketQuote(
      symbol: symbol,
      companyName: 'Apple Inc.',
      currentPrice: price,
      change: 1,
      changePercentage: 0.5,
      exchange: exchange,
      currency: 'USD',
      updatedAt: observed,
      sourceProvider: provider,
      retrievedAt: retrievedAt ?? observed.add(const Duration(seconds: 2)),
    );
  }

  http.Response portfolioResponse({double? averagePurchasePrice = 160}) {
    final costBasis = averagePurchasePrice == null
        ? ''
        : ',"averagePurchasePrice":$averagePurchasePrice';
    return http.Response(
      '{"data":{"positions":[{"id":3,"symbol":"AAPL","exchange":"NASDAQ","quantity":4.5$costBasis,"createdAt":"2026-09-10T10:00:00Z","updatedAt":"2026-09-10T10:01:00Z"}],"positionCount":1}}',
      200,
    );
  }

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

  test('load sends bearer token and parses owner-visible encrypted cost basis', () async {
    session.establish(accessToken: 'signed.jwt.token', account: account());
    late http.Request captured;
    final client = MockClient((request) async {
      captured = request;
      return http.Response(
        '{"data":{"positions":[{"id":3,"symbol":"AAPL","exchange":"NASDAQ","quantity":4.5,"averagePurchasePrice":187.25,"createdAt":"2026-09-10T10:00:00Z","updatedAt":"2026-09-10T10:01:00Z"}],"positionCount":1},"policy":{"ownerDerivedFromAuthenticatedToken":true,"sensitiveCostBasisEncrypted":true}}',
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
    expect(positions.single.averagePurchasePrice, 187.25);
  });

  test('legacy position without average purchase price remains compatible', () async {
    session.establish(accessToken: 'signed.jwt.token', account: account());
    final client = MockClient((request) async => portfolioResponse(
          averagePurchasePrice: null,
        ));
    final service = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      client: client,
      session: session,
    );

    final positions = await service.loadPositions();

    expect(positions.single.averagePurchasePrice, isNull);
  });

  test('valued positions join authenticated holdings with market data in memory', () async {
    session.establish(accessToken: 'signed.jwt.token', account: account());
    final service = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      client: MockClient((request) async => portfolioResponse()),
      session: session,
    );
    final market = _MarketRepository(quote());

    final positions = await service.loadValuedPositions(marketRepository: market);

    expect(market.requestedSymbols, ['AAPL']);
    expect(positions, hasLength(1));
    expect(positions.single.holding.id, 3);
    expect(positions.single.currentValue, 900);
    expect(positions.single.investedValue, 720);
    expect(positions.single.profitLoss, 180);
    expect(positions.single.profitLossPercentage, 25);
    expect(positions.single.quote.sourceProvider, 'yahoo_finance');
  });

  test('valued positions do not fabricate cost basis when backend has none', () async {
    session.establish(accessToken: 'signed.jwt.token', account: account());
    final service = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      client: MockClient((request) async => portfolioResponse(
            averagePurchasePrice: null,
          )),
      session: session,
    );

    final positions = await service.loadValuedPositions(
      marketRepository: _MarketRepository(quote()),
    );

    expect(positions.single.currentValue, 900);
    expect(positions.single.investedValue, isNull);
    expect(positions.single.profitLoss, isNull);
    expect(positions.single.profitLossPercentage, isNull);
  });

  test('valued positions fail closed on mismatched listing', () async {
    session.establish(accessToken: 'signed.jwt.token', account: account());
    final service = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      client: MockClient((request) async => portfolioResponse()),
      session: session,
    );

    await expectLater(
      service.loadValuedPositions(
        marketRepository: _MarketRepository(quote(exchange: 'NYSE')),
      ),
      throwsA(isA<StateError>()),
    );
  });

  test('valued positions require complete market provenance', () async {
    session.establish(accessToken: 'signed.jwt.token', account: account());
    final service = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      client: MockClient((request) async => portfolioResponse()),
      session: session,
    );

    await expectLater(
      service.loadValuedPositions(
        marketRepository: _MarketRepository(quote(provider: null)),
      ),
      throwsA(isA<StateError>()),
    );
  });

  test('valued positions reject retrieval timestamps before observation', () async {
    session.establish(accessToken: 'signed.jwt.token', account: account());
    final observed = DateTime.parse('2026-09-15T16:00:00Z');
    final service = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      client: MockClient((request) async => portfolioResponse()),
      session: session,
    );

    await expectLater(
      service.loadValuedPositions(
        marketRepository: _MarketRepository(
          quote(
            observedAt: observed,
            retrievedAt: observed.subtract(const Duration(seconds: 1)),
          ),
        ),
      ),
      throwsA(isA<StateError>()),
    );
  });

  test('upsert sends cost basis but never client owner or trading authority', () async {
    session.establish(accessToken: 'signed.jwt.token', account: account());
    late http.Request captured;
    final client = MockClient((request) async {
      captured = request;
      return http.Response(
        '{"data":{"id":4,"symbol":"MSFT","exchange":"NASDAQ","quantity":2.0,"averagePurchasePrice":405.5,"createdAt":"2026-09-10T10:00:00Z","updatedAt":"2026-09-10T10:00:00Z"}}',
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
      averagePurchasePrice: 405.5,
    );

    final body = jsonDecode(captured.body) as Map<String, dynamic>;
    expect(captured.method, 'PUT');
    expect(captured.headers['Authorization'], 'Bearer signed.jwt.token');
    expect(body['symbol'], 'MSFT');
    expect(body['exchange'], 'NASDAQ');
    expect(body['quantity'], 2.0);
    expect(body['averagePurchasePrice'], 405.5);
    expect(body.containsKey('ownerUserId'), isFalse);
    expect(body.containsKey('userId'), isFalse);
    expect(body.containsKey('currentPrice'), isFalse);
    expect(body.containsKey('capital'), isFalse);
    expect(body.containsKey('productionEligible'), isFalse);
    expect(body.containsKey('automaticTrading'), isFalse);
    expect(position.id, 4);
    expect(position.averagePurchasePrice, 405.5);
  });

  test('upsert rejects invalid average purchase price before network', () async {
    session.establish(accessToken: 'signed.jwt.token', account: account());
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

    for (final value in <double>[0, -1, double.nan, double.infinity]) {
      await expectLater(
        service.upsertPosition(
          symbol: 'MSFT',
          exchange: 'NASDAQ',
          quantity: 2,
          averagePurchasePrice: value,
        ),
        throwsArgumentError,
      );
    }
    expect(called, isFalse);
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

  test('all portfolio operations preserve authorization rejection semantics', () async {
    session.establish(accessToken: 'revoked.jwt.token', account: account());

    Future<void> expectRejected(Future<void> Function() operation) async {
      await expectLater(
        operation(),
        throwsA(
          isA<AuthSessionRejectedException>()
              .having((error) => error.statusCode, 'statusCode', 401),
        ),
      );
    }

    final service = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      client: MockClient((request) async => http.Response(
            '{"detail":"credential rejected"}',
            401,
          )),
      session: session,
    );

    await expectRejected(() async {
      await service.loadPositions();
    });
    expect(session.isAuthenticated, isFalse);
    expect(session.accessToken, isNull);
    await expectRejected(() async {
      await service.loadHistory();
    });
    await expectRejected(() async {
      await service.upsertPosition(symbol: 'AAPL', quantity: 1);
    });
    await expectRejected(() => service.deletePosition(11));
  });

  test('portfolio authorization rejection never leaks backend detail', () async {
    session.establish(accessToken: 'revoked.jwt.token', account: account());
    final service = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      client: MockClient((request) async => http.Response(
            '{"detail":"sensitive authorization diagnostic"}',
            403,
          )),
      session: session,
    );

    try {
      await service.loadPositions();
      fail('Expected authorization rejection.');
    } on AuthSessionRejectedException catch (error) {
      expect(error.statusCode, 403);
      expect(error.toString(), isNot(contains('sensitive authorization diagnostic')));
      expect(session.isAuthenticated, isFalse);
      expect(session.accessToken, isNull);
    }
  });
}
