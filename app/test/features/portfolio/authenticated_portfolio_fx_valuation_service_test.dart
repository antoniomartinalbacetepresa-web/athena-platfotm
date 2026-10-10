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
        marketSourceProvider: 'verified-market',
        marketObservedAt: observed,
        marketRetrievedAt: retrieved,
      );

  FxQuote fx({
    String base = 'USD',
    String quote = 'EUR',
    double rate = 0.9,
    String status = 'ok',
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
}
