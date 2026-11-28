import 'package:app/features/market/models/fx_quote.dart';
import 'package:app/features/portfolio/models/authenticated_portfolio_view_position.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_fx_valuation_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final observed = DateTime.parse('2026-09-16T00:00:00Z');
  final retrieved = DateTime.parse('2026-09-16T00:01:00Z');

  AuthenticatedPortfolioViewPosition position({
    required int id,
    required String symbol,
    required String? currency,
    required double currentValue,
    String provider = 'verified-market',
    DateTime? marketObservedAt,
    DateTime? marketRetrievedAt,
  }) => AuthenticatedPortfolioViewPosition(
        serverPositionId: id,
        symbol: symbol,
        companyName: symbol,
        exchange: 'NASDAQ',
        quantity: 1,
        currency: currency,
        currentPrice: currentValue,
        averagePurchasePrice: null,
        currentValue: currentValue,
        investedValue: null,
        profitLoss: null,
        profitLossPercentage: null,
        marketSourceProvider: provider,
        marketObservedAt: marketObservedAt ?? observed,
        marketRetrievedAt: marketRetrievedAt ?? retrieved,
      );

  FxQuote fx({
    String base = 'USD',
    String quote = 'EUR',
    double rate = 0.9,
    String status = 'fx_current_ready',
    String provider = 'verified-fx',
    bool pit = false,
    DateTime? observedAt,
    DateTime? retrievedAt,
  }) => FxQuote(
        baseCurrency: base,
        quoteCurrency: quote,
        rate: rate,
        status: status,
        sourceProvider: provider,
        sourceSymbol: base == quote ? null : '${base.toUpperCase()}${quote.toUpperCase()}=X',
        observedAt: observedAt ?? observed,
        retrievedAt: retrievedAt ?? retrieved,
        historicalPointInTimeEligible: pit,
      );

  test('values same-currency positions without requesting FX', () async {
    var calls = 0;
    final service = AuthenticatedPortfolioFxValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        calls += 1;
        return fx(base: baseCurrency, quote: quoteCurrency);
      },
    );

    final value = await service.value(
      positions: [
        position(id: 1, symbol: 'AAA', currency: 'EUR', currentValue: 100),
        position(id: 2, symbol: 'BBB', currency: 'EUR', currentValue: 50),
      ],
      baseCurrency: 'eur',
    );

    expect(value.baseCurrency, 'EUR');
    expect(value.currentValueInBaseCurrency, 150);
    expect(value.positionsValued, 2);
    expect(value.positionValuesInBaseCurrency, [100, 50]);
    expect(value.usesFx, isFalse);
    expect(calls, 0);
  });

  test('reuses one verified FX quote for positions sharing source currency', () async {
    var calls = 0;
    final service = AuthenticatedPortfolioFxValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        calls += 1;
        expect(baseCurrency, 'USD');
        expect(quoteCurrency, 'EUR');
        return fx();
      },
    );

    final value = await service.value(
      positions: [
        position(id: 1, symbol: 'AAA', currency: 'USD', currentValue: 100),
        position(id: 2, symbol: 'BBB', currency: 'USD', currentValue: 50),
        position(id: 3, symbol: 'CCC', currency: 'EUR', currentValue: 20),
      ],
      baseCurrency: 'EUR',
    );

    expect(value.currentValueInBaseCurrency, 155);
    expect(value.positionValuesInBaseCurrency, [90, 45, 20]);
    expect(() => value.positionValuesInBaseCurrency.add(1), throwsUnsupportedError);
    expect(value.fxEvidence, hasLength(1));
    expect(calls, 1);
  });

  test('fails closed when a position has no verifiable ISO currency', () async {
    final service = AuthenticatedPortfolioFxValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async => fx(),
    );

    expect(
      () => service.value(
        positions: [position(id: 1, symbol: 'AAA', currency: null, currentValue: 100)],
        baseCurrency: 'EUR',
      ),
      throwsA(isA<StateError>()),
    );
  });

  test('rejects FX evidence for a different requested pair', () async {
    final service = AuthenticatedPortfolioFxValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async =>
          fx(base: 'GBP', quote: 'EUR'),
    );

    await expectLater(
      service.value(
        positions: [position(id: 1, symbol: 'AAA', currency: 'USD', currentValue: 100)],
        baseCurrency: 'EUR',
      ),
      throwsA(isA<StateError>()),
    );
  });

  test('rejects current FX falsely labelled historical PIT evidence', () {
    expect(
      () => fx(pit: true),
      throwsA(isA<ArgumentError>()),
    );
  });

  test('rejects FX retrieval timestamp before observation', () {
    expect(
      () => fx(observedAt: retrieved, retrievedAt: observed),
      throwsA(isA<ArgumentError>()),
    );
  });

  test('historical PIT FX cannot value current authenticated holdings', () async {
    final historical = FxQuote(
      baseCurrency: 'USD',
      quoteCurrency: 'EUR',
      rate: 0.9,
      status: 'fx_historical_ready',
      sourceProvider: 'verified-fx',
      sourceSymbol: 'USDEUR=X',
      observedAt: observed,
      retrievedAt: retrieved,
      historicalPointInTimeEligible: true,
    );
    expect(() => historical.convertCurrent(100), throwsA(isA<StateError>()));
    final service = AuthenticatedPortfolioFxValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async =>
          historical,
    );
    await expectLater(
      service.value(
        positions: [position(id: 1, symbol: 'AAA', currency: 'USD', currentValue: 100)],
        baseCurrency: 'EUR',
      ),
      throwsA(isA<StateError>()),
    );
  });
  test('authenticated same-currency valuation rejects FMP source', () async {
    final service = AuthenticatedPortfolioFxValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        fail('Same-currency positions must not request FX');
      },
    );
    await expectLater(
      service.value(
        positions: [position(id: 8, symbol: 'BLOCKED', currency: 'EUR',
            currentValue: 100, provider: 'financial-modeling-prep')],
        baseCurrency: 'EUR',
      ),
      throwsStateError,
    );
  });

  test('authenticated valuation rejects ambiguous encoded source', () async {
    final service = AuthenticatedPortfolioFxValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        fail('Same-currency positions must not request FX');
      },
    );
    await expectLater(
      service.value(
        positions: [position(id: 9, symbol: 'BLOCKED', currency: 'EUR',
            currentValue: 100, provider: 'yahoo%2Ffinance')],
        baseCurrency: 'EUR',
      ),
      throwsStateError,
    );
  });

  test('authenticated same-currency valuation rejects trailing control provider', () async {
    final service = AuthenticatedPortfolioFxValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        fail('Same-currency positions must not request FX');
      },
    );
    await expectLater(
      service.value(positions: [
        position(id: 11, symbol: 'CONTROL', currency: 'EUR',
            currentValue: 100, provider: 'yahoo\n'),
      ], baseCurrency: 'EUR'),
      throwsStateError,
    );
  });

  test('authenticated same-currency valuation rejects future market observation', () async {
    final service = AuthenticatedPortfolioFxValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        fail('Same-currency positions must not request FX');
      },
    );
    await expectLater(
      service.value(positions: [
        position(id: 12, symbol: 'FUTURE', currency: 'EUR',
            currentValue: 100, marketObservedAt: DateTime.utc(2099, 1, 1),
            marketRetrievedAt: DateTime.utc(2099, 1, 2)),
      ], baseCurrency: 'EUR'),
      throwsStateError,
    );
  });

  test('authenticated FX valuation rejects future FX retrieval', () async {
    final service = AuthenticatedPortfolioFxValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async =>
          fx(retrievedAt: DateTime.utc(2099, 1, 1)),
    );
    await expectLater(
      service.value(positions: [
        position(id: 13, symbol: 'FX-FUTURE', currency: 'USD',
            currentValue: 100),
      ], baseCurrency: 'EUR'),
      throwsStateError,
    );
  });


}
