import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/repositories/market_repository.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class _QuoteRepository implements MarketRepository {
  _QuoteRepository(this.quote);

  final MarketQuote quote;

  @override
  Future<MarketQuote> getQuote(String symbol) async => quote;
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

  AuthenticatedPortfolioService serviceFor({double? averagePurchasePrice = 100}) {
    session.establish(accessToken: 'signed.jwt.token', account: account());
    final costBasis = averagePurchasePrice == null
        ? ''
        : ',"averagePurchasePrice":$averagePurchasePrice';
    return AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      session: session,
      client: MockClient((request) async => http.Response(
            '{"data":{"positions":[{"id":3,"symbol":"AAPL","exchange":"NASDAQ","quantity":2$costBasis,"createdAt":"2026-09-10T10:00:00Z","updatedAt":"2026-09-10T10:01:00Z"}],"positionCount":1}}',
            200,
          )),
    );
  }

  MarketQuote quote({
    String symbol = 'AAPL',
    String? exchange = 'NASDAQ',
    String? provider = 'yahoo_finance',
    DateTime? retrievedAt,
    double currentPrice = 125,
  }) {
    final observedAt = DateTime.parse('2026-09-15T15:00:00Z');
    return MarketQuote(
      symbol: symbol,
      companyName: 'Apple Inc.',
      currentPrice: currentPrice,
      change: 1,
      changePercentage: 0.8,
      exchange: exchange,
      updatedAt: observedAt,
      sourceProvider: provider,
      retrievedAt: retrievedAt ?? observedAt.add(const Duration(seconds: 2)),
    );
  }

  test('joins owner holding with market quote and computes valuation in memory', () async {
    final service = serviceFor();

    final valued = await service.loadValuedPositions(
      marketRepository: _QuoteRepository(quote()),
    );

    expect(valued, hasLength(1));
    expect(valued.single.holding.quantity, 2);
    expect(valued.single.currentValue, 250);
    expect(valued.single.investedValue, 200);
    expect(valued.single.profitLoss, 50);
    expect(valued.single.profitLossPercentage, 25);
  });

  test('unknown historical cost basis stays unknown instead of being fabricated', () async {
    final service = serviceFor(averagePurchasePrice: null);

    final valued = await service.loadValuedPositions(
      marketRepository: _QuoteRepository(quote()),
    );

    expect(valued.single.currentValue, 250);
    expect(valued.single.investedValue, isNull);
    expect(valued.single.profitLoss, isNull);
    expect(valued.single.profitLossPercentage, isNull);
  });

  test('rejects quote from a different listing', () async {
    final service = serviceFor();

    await expectLater(
      service.loadValuedPositions(
        marketRepository: _QuoteRepository(quote(exchange: 'NYSE')),
      ),
      throwsStateError,
    );
  });

  test('rejects quote without provider provenance', () async {
    final service = serviceFor();

    await expectLater(
      service.loadValuedPositions(
        marketRepository: _QuoteRepository(quote(provider: null)),
      ),
      throwsStateError,
    );
  });

  test('rejects market retrieval timestamp before observation', () async {
    final service = serviceFor();

    await expectLater(
      service.loadValuedPositions(
        marketRepository: _QuoteRepository(
          quote(retrievedAt: DateTime.parse('2026-09-15T14:59:59Z')),
        ),
      ),
      throwsStateError,
    );
  });
}
