import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/presentation/widgets/verified_market_quote_panel.dart';
import 'package:app/features/market/repositories/market_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class _QuoteRepository implements MarketRepository {
  _QuoteRepository(this.quote);
  final MarketQuote quote;

  @override
  Future<MarketQuote> getQuote(String symbol) async => quote;
}

MarketQuote _quote({bool? realtime, bool? pit}) {
  final now = DateTime.now().toUtc();
  return MarketQuote(
    symbol: 'MSFT',
    companyName: 'Microsoft',
    currentPrice: 200,
    change: 0,
    changePercentage: 0,
    currency: 'USD',
    exchange: 'NASDAQ',
    updatedAt: now.subtract(const Duration(minutes: 1)),
    retrievedAt: now,
    sourceProvider: 'test_provider',
    canonicalIdentityStatus: 'unresolved',
    realTimePriceVerified: realtime,
    historicalPointInTimeEligible: pit,
  );
}

void main() {
  testWidgets('unverified quote never implies licensed or PIT historical data',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: VerifiedMarketQuotePanel(
          symbol: 'MSFT',
          repository: _QuoteRepository(_quote(realtime: false, pit: false)),
        ),
      ),
    ));
    await tester.tap(find.byKey(const Key('market-quote-request')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('market-quote-price')), findsOneWidget);
    expect(find.textContaining('Tiempo real: NO VERIFICADO'), findsOneWidget);
    expect(find.textContaining('Elegibilidad PIT histórica: NO ACREDITADA'),
        findsOneWidget);
    expect(find.textContaining('Derechos de uso y redistribución: NO VERIFICADOS'),
        findsOneWidget);
  });

  testWidgets('provider-declared verification does not imply independent rights',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: VerifiedMarketQuotePanel(
          symbol: 'MSFT',
          repository: _QuoteRepository(_quote(realtime: true, pit: true)),
        ),
      ),
    ));
    await tester.tap(find.byKey(const Key('market-quote-request')));
    await tester.pumpAndSettle();

    expect(find.textContaining('no acreditada independientemente'),
        findsOneWidget);
    expect(find.textContaining('NO acredita licencia'), findsOneWidget);
    expect(find.byKey(const Key('market-quote-license-boundary')),
        findsOneWidget);
  });
}
