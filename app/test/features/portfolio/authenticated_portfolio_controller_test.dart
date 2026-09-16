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

  http.Response portfolioResponse({double? averagePurchasePrice = 160}) =>
      http.Response(
        jsonEncode({
          'data': {
            'positions': [
              {
                'id': 3,
                'symbol': 'AAPL',
                'exchange': 'NASDAQ',
                'quantity': 4.5,
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
}
