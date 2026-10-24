import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/portfolio/models/authenticated_portfolio_position.dart';
import 'package:app/features/portfolio/models/authenticated_portfolio_view_position.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final observedAt = DateTime.parse('2026-09-15T16:00:00Z');
  final retrievedAt = DateTime.parse('2026-09-15T16:00:02Z');

  AuthenticatedPortfolioValuedPosition valued({
    int id = 3,
    String symbol = 'AAPL',
    String? exchange = 'NASDAQ',
    double quantity = 4.5,
    double? averagePurchasePrice = 160,
    String? currency = 'USD',
    String? provider = 'yahoo_finance',
    DateTime? retrieved,
  }) {
    return AuthenticatedPortfolioValuedPosition(
      holding: AuthenticatedPortfolioPosition(
        id: id,
        symbol: symbol,
        exchange: exchange,
        quantity: quantity,
        averagePurchasePrice: averagePurchasePrice,
        createdAt: DateTime.parse('2026-09-10T10:00:00Z'),
        updatedAt: DateTime.parse('2026-09-10T10:01:00Z'),
      ),
      quote: MarketQuote(
        symbol: symbol,
        companyName: 'Apple Inc.',
        currentPrice: 200,
        change: 1,
        changePercentage: 0.5,
        currency: currency,
        exchange: exchange,
        updatedAt: observedAt,
        sourceProvider: provider,
        retrievedAt: retrieved ?? retrievedAt,
      ),
    );
  }

  test('projection preserves owner position id and verified market provenance', () {
    final position = AuthenticatedPortfolioViewPosition.fromValuedPosition(
      valued(),
    );

    expect(position.serverPositionId, 3);
    expect(position.symbol, 'AAPL');
    expect(position.companyName, 'Apple Inc.');
    expect(position.quantity, 4.5);
    expect(position.currency, 'USD');
    expect(position.currentValue, 900);
    expect(position.investedValue, 720);
    expect(position.profitLoss, 180);
    expect(position.profitLossPercentage, 25);
    expect(position.marketSourceProvider, 'yahoo_finance');
    expect(position.marketObservedAt, observedAt);
    expect(position.marketRetrievedAt, retrievedAt);
    expect(position.hasCostBasis, isTrue);
  });

  test('projection never fabricates missing authenticated cost basis', () {
    final position = AuthenticatedPortfolioViewPosition.fromValuedPosition(
      valued(averagePurchasePrice: null),
    );

    expect(position.currentValue, 900);
    expect(position.averagePurchasePrice, isNull);
    expect(position.investedValue, isNull);
    expect(position.profitLoss, isNull);
    expect(position.profitLossPercentage, isNull);
    expect(position.hasCostBasis, isFalse);
  });

  test('projection fails closed without complete market provenance', () {
    expect(
      () => AuthenticatedPortfolioViewPosition.fromValuedPosition(
        valued(provider: null),
      ),
      throwsA(isA<StateError>()),
    );
  });

  test('projection rejects retrieval before market observation', () {
    expect(
      () => AuthenticatedPortfolioViewPosition.fromValuedPosition(
        valued(retrieved: observedAt.subtract(const Duration(seconds: 1))),
      ),
      throwsA(isA<StateError>()),
    );
  });

  test('commonCurrency allows only directly comparable verified quote units', () {
    final usdA = AuthenticatedPortfolioViewPosition.fromValuedPosition(valued());
    final usdB = AuthenticatedPortfolioViewPosition.fromValuedPosition(
      valued(id: 4, symbol: 'MSFT', quantity: 2),
    );
    final eur = AuthenticatedPortfolioViewPosition.fromValuedPosition(
      valued(id: 5, symbol: 'SAP', exchange: 'XETRA', currency: 'EUR'),
    );
    final unknown = AuthenticatedPortfolioViewPosition.fromValuedPosition(
      valued(id: 6, symbol: 'BRK-B', currency: null),
    );

    expect(
      AuthenticatedPortfolioViewPosition.commonCurrency([usdA, usdB]),
      'USD',
    );
    expect(
      AuthenticatedPortfolioViewPosition.commonCurrency([usdA, eur]),
      isNull,
    );
    expect(
      AuthenticatedPortfolioViewPosition.commonCurrency([usdA, unknown]),
      isNull,
    );
    expect(
      AuthenticatedPortfolioViewPosition.commonCurrency(const []),
      isNull,
    );
  });
}
