import 'dart:async';

import 'package:app/features/market/models/fx_quote.dart';
import 'package:app/features/portfolio/models/authenticated_portfolio_view_position.dart';
import 'package:app/features/portfolio/presentation/controllers/authenticated_portfolio_fx_valuation_controller.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_fx_valuation_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final observed = DateTime.parse('2026-09-16T00:00:00Z');
  final retrieved = DateTime.parse('2026-09-16T00:01:00Z');

  AuthenticatedPortfolioViewPosition position({
    required String currency,
    required double currentValue,
  }) => AuthenticatedPortfolioViewPosition(
        serverPositionId: 1,
        symbol: 'AAA',
        companyName: 'AAA',
        exchange: 'NASDAQ',
        quantity: 1,
        currency: currency,
        currentPrice: currentValue,
        averagePurchasePrice: null,
        currentValue: currentValue,
        investedValue: null,
        profitLoss: null,
        profitLossPercentage: null,
        marketSourceProvider: 'verified-market',
        marketObservedAt: observed,
        marketRetrievedAt: retrieved,
      );

  FxQuote fx(
    double rate, {
    String baseCurrency = 'USD',
    String quoteCurrency = 'EUR',
  }) => FxQuote(
        baseCurrency: baseCurrency,
        quoteCurrency: quoteCurrency,
        rate: rate,
        status: 'ok',
        sourceProvider: 'verified-fx',
        observedAt: observed,
        retrievedAt: retrieved,
        historicalPointInTimeEligible: false,
      );

  test('verified load exposes valuation and clears loading/error', () async {
    final controller = AuthenticatedPortfolioFxValuationController(
      valuationService: AuthenticatedPortfolioFxValuationService(
        loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async => fx(0.9),
      ),
    );

    await controller.load(
      positions: [position(currency: 'USD', currentValue: 100)],
      baseCurrency: 'EUR',
    );

    expect(controller.isLoading, isFalse);
    expect(controller.error, isNull);
    expect(controller.hasVerifiedValuation, isTrue);
    expect(controller.valuation!.currentValueInBaseCurrency, 90);
  });

  test('authoritative failure removes a previously verified valuation', () async {
    var fail = false;
    final controller = AuthenticatedPortfolioFxValuationController(
      valuationService: AuthenticatedPortfolioFxValuationService(
        loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
          if (fail) throw StateError('temporary failure');
          return fx(0.9);
        },
      ),
    );

    await controller.load(
      positions: [position(currency: 'USD', currentValue: 100)],
      baseCurrency: 'EUR',
    );
    expect(controller.hasVerifiedValuation, isTrue);

    fail = true;
    await controller.load(
      positions: [position(currency: 'USD', currentValue: 100)],
      baseCurrency: 'EUR',
    );

    expect(controller.hasVerifiedValuation, isFalse);
    expect(controller.valuation, isNull);
    expect(controller.error, isNotNull);
  });

  test('Profile base-currency change cannot retain valuation in the old currency', () async {
    final controller = AuthenticatedPortfolioFxValuationController(
      valuationService: AuthenticatedPortfolioFxValuationService(
        loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
          if (quoteCurrency == 'EUR') {
            return fx(0.9, baseCurrency: baseCurrency, quoteCurrency: quoteCurrency);
          }
          throw StateError('GBP authority unavailable');
        },
      ),
    );
    final positions = [position(currency: 'USD', currentValue: 100)];

    await controller.load(positions: positions, baseCurrency: 'EUR');
    expect(controller.hasVerifiedValuation, isTrue);
    expect(controller.valuation!.baseCurrency, 'EUR');
    expect(controller.valuation!.currentValueInBaseCurrency, 90);

    await controller.load(positions: positions, baseCurrency: 'GBP');

    expect(controller.hasVerifiedValuation, isFalse);
    expect(controller.valuation, isNull);
    expect(controller.error, isNotNull);
  });

  test('clear invalidates an in-flight result and removes monetary state', () async {
    final pending = Completer<FxQuote>();
    final controller = AuthenticatedPortfolioFxValuationController(
      valuationService: AuthenticatedPortfolioFxValuationService(
        loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) => pending.future,
      ),
    );

    final load = controller.load(
      positions: [position(currency: 'USD', currentValue: 100)],
      baseCurrency: 'EUR',
    );
    expect(controller.isLoading, isTrue);

    controller.clear();
    expect(controller.isLoading, isFalse);
    expect(controller.valuation, isNull);
    expect(controller.error, isNull);

    pending.complete(fx(0.9));
    await load;

    expect(controller.hasVerifiedValuation, isFalse);
    expect(controller.valuation, isNull);
  });

  test('newer load wins when an older FX request completes later', () async {
    final first = Completer<FxQuote>();
    var calls = 0;
    final controller = AuthenticatedPortfolioFxValuationController(
      valuationService: AuthenticatedPortfolioFxValuationService(
        loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) {
          calls += 1;
          if (calls == 1) return first.future;
          return Future.value(fx(0.8));
        },
      ),
    );

    final older = controller.load(
      positions: [position(currency: 'USD', currentValue: 100)],
      baseCurrency: 'EUR',
    );
    final newer = controller.load(
      positions: [position(currency: 'USD', currentValue: 100)],
      baseCurrency: 'EUR',
    );
    await newer;
    expect(controller.valuation!.currentValueInBaseCurrency, 80);

    first.complete(fx(0.9));
    await older;

    expect(controller.valuation!.currentValueInBaseCurrency, 80);
    expect(controller.hasVerifiedValuation, isTrue);
  });
}
