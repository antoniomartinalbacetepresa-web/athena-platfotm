import 'dart:async';

import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/presentation/widgets/verified_market_quote_panel.dart';
import 'package:app/features/market/repositories/market_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class _QueuedQuotes implements MarketRepository {
  _QueuedQuotes(this.responses);

  final List<Future<MarketQuote>> responses;
  int calls = 0;

  @override
  Future<MarketQuote> getQuote(String symbol) => responses[calls++];
}

MarketQuote _quote(String symbol, {String companyName = 'Example Company'}) {
  final now = DateTime.now().toUtc();
  return MarketQuote(
    symbol: symbol,
    companyName: companyName,
    currentPrice: 100,
    change: 1,
    changePercentage: 1,
    currency: 'USD',
    exchange: 'NASDAQ',
    updatedAt: now.subtract(const Duration(minutes: 2)),
    retrievedAt: now,
    sourceProvider: 'declared-test-provider',
    instrumentId: 123,
    canonicalIdentityStatus: 'matched_internal_listing',
  );
}

void main() {
  testWidgets('Late quote from prior symbol cannot replace the selected instrument',
      (tester) async {
    final stale = Completer<MarketQuote>();
    final repository = _QueuedQuotes([
      stale.future,
      Future.value(_quote('MSFT')),
    ]);
    final validated = <String>[];

    Future<void> render(String symbol) => tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: VerifiedMarketQuotePanel(
                symbol: symbol,
                repository: repository,
                onQuoteValidated: (ticker, _) => validated.add(ticker),
              ),
            ),
          ),
        );

    await render('AAPL');
    await tester.tap(find.byKey(const Key('market-quote-request')));
    await tester.pump();
    expect(repository.calls, 1);

    await render('MSFT');
    await tester.tap(find.byKey(const Key('market-quote-request')));
    await tester.pumpAndSettle();
    expect(find.textContaining('MSFT · 100.00 USD'), findsOneWidget);
    expect(validated, ['MSFT']);

    stale.complete(_quote('AAPL'));
    await tester.pumpAndSettle();
    expect(find.textContaining('AAPL · 100.00 USD'), findsNothing);
    expect(find.textContaining('MSFT · 100.00 USD'), findsOneWidget);
    expect(validated, ['MSFT']);
  });

  testWidgets('Unverifiable quote fails closed and retry recovers without provider error',
      (tester) async {
    final failing = Completer<MarketQuote>();
    final repository = _QueuedQuotes([
      failing.future,
      Future.value(_quote('MSFT')),
    ]);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: VerifiedMarketQuotePanel(symbol: 'MSFT', repository: repository),
        ),
      ),
    );
    await tester.tap(find.byKey(const Key('market-quote-request')));
    await tester.pump();
    failing.completeError(const FormatException('provider token=private'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('market-quote-error')), findsOneWidget);
    expect(find.textContaining('token=private'), findsNothing);
    expect(find.byKey(const Key('market-quote-price')), findsNothing);

    await tester.tap(find.byKey(const Key('market-quote-request')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('market-quote-error')), findsNothing);
    expect(find.byKey(const Key('market-quote-price')), findsOneWidget);
    expect(find.byKey(const Key('market-quote-license-boundary')), findsOneWidget);
    expect(find.byKey(const Key('market-quote-age')), findsOneWidget);
    expect(find.textContaining('Antigüedad de observación:'), findsOneWidget);
    expect(find.textContaining('Antigüedad de observación: 2 minutos'), findsOneWidget);
    expect(find.textContaining('antigüedad de recuperación: 0 minutos'), findsOneWidget);
    expect(repository.calls, 2);
  });
  testWidgets('Historical fallback rejects malformed and future session dates',
      (tester) async {
    final now = DateTime.now().toUtc();
    MarketQuote fallback(String session) => MarketQuote(
          symbol: 'MSFT',
          companyName: 'Example Company',
          currentPrice: 100,
          change: 0,
          changePercentage: 0,
          currency: 'USD',
          exchange: 'NASDAQ',
          updatedAt: now.subtract(const Duration(days: 2)),
          retrievedAt: now,
          sourceProvider: 'declared-test-provider',
          quoteMode: 'historical_daily_close_fallback',
          priceSessionDate: session,
          instrumentId: 123,
          canonicalIdentityStatus: 'matched_internal_listing',
        );
    final repository = _QueuedQuotes([
      Future.value(fallback('2026-02-30')),
      Future.value(fallback(now.add(const Duration(days: 1))
          .toIso8601String().substring(0, 10))),
      Future.value(fallback(now.subtract(const Duration(days: 3))
          .toIso8601String().substring(0, 10))),
    ]);
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: VerifiedMarketQuotePanel(symbol: 'MSFT', repository: repository),
      ),
    ));
    for (var attempt = 0; attempt < 2; attempt++) {
      await tester.tap(find.byKey(const Key('market-quote-request')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('market-quote-error')), findsOneWidget);
      expect(find.byKey(const Key('market-quote-price')), findsNothing);
    }
    await tester.tap(find.byKey(const Key('market-quote-request')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('market-quote-price')), findsOneWidget);
    expect(find.textContaining('Antigüedad de observación: 2 días'), findsOneWidget);
    expect(repository.calls, 3);
  });

}
