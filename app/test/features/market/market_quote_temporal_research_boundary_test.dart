import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/presentation/widgets/verified_market_quote_panel.dart';
import 'package:app/features/market/repositories/market_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class _Repository implements MarketRepository {
  const _Repository(this.quote);
  final MarketQuote quote;

  @override
  Future<MarketQuote> getQuote(String symbol) async => quote;
}

void main() {
  Future<void> verifyRejected(WidgetTester tester, MarketQuote quote) async {
    var validated = false;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: VerifiedMarketQuotePanel(
          symbol: 'MSFT',
          repository: _Repository(quote),
          onQuoteValidated: (_, _) => validated = true,
          onOpenResearch: (_, _) {},
        ),
      ),
    ));
    await tester.tap(find.byKey(const Key('market-quote-request')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('market-quote-error')), findsOneWidget);
    expect(find.byKey(const Key('market-quote-price')), findsNothing);
    expect(find.byKey(const Key('market-quote-open-research')), findsNothing);
    expect(validated, isFalse);
  }

  testWidgets('future observation cannot be promoted to verified quote', (tester) async {
    final now = DateTime.now().toUtc();
    await verifyRejected(tester, MarketQuote(
      symbol: 'MSFT', companyName: 'Microsoft', currentPrice: 200,
      change: 0, changePercentage: 0, currency: 'USD',
      updatedAt: now.add(const Duration(days: 1)),
      retrievedAt: now, sourceProvider: 'fixture',
    ));
  });

  testWidgets('future retrieval cannot be promoted to verified quote', (tester) async {
    final now = DateTime.now().toUtc();
    await verifyRejected(tester, MarketQuote(
      symbol: 'MSFT', companyName: 'Microsoft', currentPrice: 200,
      change: 0, changePercentage: 0, currency: 'USD',
      updatedAt: now.subtract(const Duration(minutes: 1)),
      retrievedAt: now.add(const Duration(days: 1)),
      sourceProvider: 'fixture',
    ));
  });

  testWidgets('wrong instrument symbol cannot open research', (tester) async {
    final now = DateTime.now().toUtc();
    await verifyRejected(tester, MarketQuote(
      symbol: 'AAPL', companyName: 'Apple', currentPrice: 200,
      change: 0, changePercentage: 0, currency: 'USD',
      updatedAt: now.subtract(const Duration(minutes: 1)),
      retrievedAt: now, sourceProvider: 'fixture',
    ));
  });
}
