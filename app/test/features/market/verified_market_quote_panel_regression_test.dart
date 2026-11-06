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
    expect(repository.calls, 2);
  });
}
