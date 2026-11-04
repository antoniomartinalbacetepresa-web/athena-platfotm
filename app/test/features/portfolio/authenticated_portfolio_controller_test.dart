import 'dart:async';
import 'dart:convert';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/repositories/market_repository.dart';
import 'package:app/features/portfolio/presentation/controllers/authenticated_portfolio_controller.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class _TokenStore implements AuthTokenStore {
  @override
  Future<void> deleteAccessToken() async {}

  @override
  Future<String?> readAccessToken() async => null;

  @override
  Future<void> writeAccessToken(String token) async {}
}

class _MarketRepository implements MarketRepository {
  _MarketRepository(this.quotes);
  final Map<String, MarketQuote> quotes;

  @override
  Future<MarketQuote> getQuote(String symbol) async => quotes[symbol]!;
}

void main() {
  AuthSession session() {
    final value = AuthSession.forTesting(_TokenStore());
    value.establish(
      accessToken: 'token',
      account: AuthAccount(
        id: 7,
        email: 'owner@example.com',
        displayName: 'Owner',
        isActive: true,
        createdAt: DateTime.parse('2026-09-15T10:00:00Z'),
        updatedAt: DateTime.parse('2026-09-15T10:00:00Z'),
      ),
    );
    return value;
  }

  MarketQuote quote(String symbol, {String currency = 'USD'}) => MarketQuote(
        symbol: symbol,
        companyName: symbol,
        currentPrice: 200,
        change: 1,
        changePercentage: 0.5,
        currency: currency,
        exchange: 'NASDAQ',
        updatedAt: DateTime.parse('2026-09-15T16:00:00Z'),
        sourceProvider: 'yahoo_finance',
        retrievedAt: DateTime.parse('2026-09-15T16:00:02Z'),
      );

  http.Response portfolioResponse({double? averagePurchasePrice = 160, double quantity = 4.5}) =>
      http.Response(
        jsonEncode({
          'data': {
            'positions': [
              {
                'id': 3,
                'symbol': 'AAPL',
                'exchange': 'NASDAQ',
                'quantity': quantity,
                'averagePurchasePrice': averagePurchasePrice,
                'createdAt': '2026-09-10T10:00:00Z',
                'updatedAt': '2026-09-10T10:01:00Z',
              }
            ]
          }
        }),
        200,
        headers: {'content-type': 'application/json'},
      );

  test('load exposes only server holdings joined with verified market data', () async {
    final auth = session();
    final service = AuthenticatedPortfolioService(
      client: MockClient((request) async => portfolioResponse()),
      session: auth,
    );
    final controller = AuthenticatedPortfolioController(
      portfolioService: service,
      marketRepository: _MarketRepository({'AAPL': quote('AAPL')}),
    );

    await controller.load();

    expect(controller.sessionRejected, isFalse);
    expect(controller.error, isNull);
    expect(controller.positions, hasLength(1));
    expect(controller.positions.single.serverPositionId, 3);
    expect(controller.positions.single.currentValue, 900);
    expect(controller.positions.single.investedValue, 720);
    expect(controller.directlyComparableCurrency, 'USD');
    expect(controller.directlyComparableCurrentValue, 900);
    expect(controller.directlyComparableInvestedValue, 720);
  });

  test('load preserves unknown cost basis instead of manufacturing P/L', () async {
    final service = AuthenticatedPortfolioService(
      client: MockClient(
        (request) async => portfolioResponse(averagePurchasePrice: null),
      ),
      session: session(),
    );
    final controller = AuthenticatedPortfolioController(
      portfolioService: service,
      marketRepository: _MarketRepository({'AAPL': quote('AAPL')}),
    );

    await controller.load();

    expect(controller.positions.single.averagePurchasePrice, isNull);
    expect(controller.positions.single.profitLoss, isNull);
    expect(controller.directlyComparableInvestedValue, isNull);
  });

  test('401 clears stale positions and enters explicit rejected state', () async {
    var calls = 0;
    final auth = session();
    final service = AuthenticatedPortfolioService(
      client: MockClient((request) async {
        calls += 1;
        if (calls == 1) return portfolioResponse();
        return http.Response(jsonEncode({'detail': 'invalid session'}), 401);
      }),
      session: auth,
    );
    final controller = AuthenticatedPortfolioController(
      portfolioService: service,
      marketRepository: _MarketRepository({'AAPL': quote('AAPL')}),
    );

    await controller.load();
    expect(controller.positions, isNotEmpty);

    await controller.load();

    expect(controller.positions, isEmpty);
    expect(controller.sessionRejected, isTrue);
    expect(controller.error, isNull);
    expect(auth.isAuthenticated, isFalse);
  });

  test('authoritative reload failure never leaves stale owner holdings visible', () async {
    var calls = 0;
    final service = AuthenticatedPortfolioService(
      client: MockClient((request) async {
        calls += 1;
        if (calls == 1) return portfolioResponse();
        return http.Response(jsonEncode({'detail': 'temporary failure'}), 503);
      }),
      session: session(),
    );
    final controller = AuthenticatedPortfolioController(
      portfolioService: service,
      marketRepository: _MarketRepository({'AAPL': quote('AAPL')}),
    );

    await controller.load();
    expect(controller.positions, isNotEmpty);

    await controller.load();

    expect(controller.positions, isEmpty);
    expect(controller.sessionRejected, isFalse);
    expect(controller.error, isNotNull);
  });
  test('disposed owner holdings controller ignores late HTTP completion', () async {
    final response = Completer<http.Response>();
    final service = AuthenticatedPortfolioService(
      client: MockClient((_) => response.future),
      session: session(),
    );
    final controller = AuthenticatedPortfolioController(
      portfolioService: service,
      marketRepository: _MarketRepository({'AAPL': quote('AAPL')}),
    );
    final pending = controller.load();
    controller.dispose();
    response.complete(portfolioResponse());
    await pending;
    service.dispose();
  });


  test('disposed holdings boundary refuses later reads and writes', () async {
    final auth = session();
    var requests = 0;
    final service = AuthenticatedPortfolioService(
      session: auth,
      client: MockClient((request) async {
        requests++;
        if (request.method == 'GET') return portfolioResponse();
        return http.Response('{}', 500);
      }),
    );
    final controller = AuthenticatedPortfolioController(
      portfolioService: service,
      marketRepository: _MarketRepository({'AAPL': quote('AAPL')}),
      session: auth,
    );
    await controller.load();
    final previouslyVisible = controller.positions.single;
    expect(requests, 1);
    controller.dispose();
    expect(controller.positions, isEmpty);

    await controller.load();
    expect(await controller.upsert(symbol: 'AAPL', quantity: 3), isFalse);
    expect(await controller.remove(previouslyVisible), isFalse);
    expect(requests, 1);
    service.dispose();
  });

  test('post-mutation refresh supersedes an in-flight holdings read',
      () async {
    final auth = session();
    final oldResponse = Completer<http.Response>();
    var reads = 0;
    final service = AuthenticatedPortfolioService(
      session: auth,
      client: MockClient((request) {
        if (request.method == 'PUT') {
          final updated = (jsonDecode(portfolioResponse(quantity: 9).body)
              as Map<String, dynamic>)['data']['positions'][0];
          return Future.value(http.Response(jsonEncode({'data': updated}), 200));
        }
        expect(request.method, 'GET');
        reads++;
        return reads == 1
            ? oldResponse.future
            : Future.value(portfolioResponse(quantity: 9));
      }),
    );
    final controller = AuthenticatedPortfolioController(
      portfolioService: service,
      marketRepository: _MarketRepository({'AAPL': quote('AAPL')}),
      session: auth,
    );
    final oldLoad = controller.load();
    await Future<void>.delayed(Duration.zero);
    expect(reads, 1);

    final saved = await controller.upsert(symbol: 'AAPL', quantity: 9);
    expect(saved, isTrue);
    expect(reads, 2);
    expect(controller.positions.single.quantity, 9);
    expect(controller.positions.single.currentValue, 1800);

    oldResponse.complete(portfolioResponse());
    await oldLoad;
    expect(controller.positions.single.quantity, 9);
    expect(controller.isLoading, isFalse);
    controller.dispose();
    service.dispose();
  });

  test('failed post-mutation refresh does not report success or restore stale data',
      () async {
    final auth = session();
    final oldResponse = Completer<http.Response>();
    var reads = 0;
    final service = AuthenticatedPortfolioService(
      session: auth,
      client: MockClient((request) {
        if (request.method == 'PUT') {
          final updated = (jsonDecode(portfolioResponse(quantity: 9).body)
              as Map<String, dynamic>)['data']['positions'][0];
          return Future.value(http.Response(jsonEncode({'data': updated}), 200));
        }
        expect(request.method, 'GET');
        reads++;
        return reads == 1
            ? oldResponse.future
            : Future.value(http.Response('unavailable', 503));
      }),
    );
    final controller = AuthenticatedPortfolioController(
      portfolioService: service,
      marketRepository: _MarketRepository({'AAPL': quote('AAPL')}),
      session: auth,
    );
    final oldLoad = controller.load();
    await Future<void>.delayed(Duration.zero);
    expect(reads, 1);

    expect(await controller.upsert(symbol: 'AAPL', quantity: 9), isFalse);
    expect(reads, 2);
    expect(controller.positions, isEmpty);
    expect(controller.error, isNotNull);

    oldResponse.complete(portfolioResponse());
    await oldLoad;
    expect(controller.positions, isEmpty);
    expect(controller.error, isNotNull);
    controller.dispose();
    service.dispose();
  });

}
