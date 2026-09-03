import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/models/fx_quote.dart';
import 'package:app/features/portfolio/models/portfolio_position.dart';
import 'package:app/features/portfolio/services/portfolio_current_valuation_service.dart';

PortfolioPosition position({
  required String symbol,
  required String currency,
  double shares = 2,
  double averagePrice = 100,
  double currentPrice = 120,
}) {
  return PortfolioPosition(
    symbol: symbol,
    companyName: '$symbol Company',
    shares: shares,
    averagePrice: averagePrice,
    currentPrice: currentPrice,
    priceCurrency: currency,
  );
}

FxQuote usdEur({double rate = 0.85}) {
  final observedAt = DateTime.utc(2026, 9, 3, 0, 0);
  return FxQuote(
    status: 'ok',
    baseCurrency: 'USD',
    quoteCurrency: 'EUR',
    rate: rate,
    observedAt: observedAt,
    retrievedAt: observedAt.add(const Duration(seconds: 1)),
    sourceProvider: 'yahoo',
    sourceSymbol: 'USDEUR=X',
    historicalPointInTimeEligible: false,
  );
}

void main() {
  test('values same-currency portfolio without FX and keeps historical P/L', () async {
    var fxCalls = 0;
    final service = PortfolioCurrentValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        fxCalls += 1;
        throw StateError('FX should not be requested');
      },
    );

    final valuation = await service.value(
      positions: [
        position(
          symbol: 'EUR1',
          currency: 'EUR',
          shares: 2,
          averagePrice: 100,
          currentPrice: 120,
        ),
      ],
    );

    expect(fxCalls, 0);
    expect(valuation.baseCurrency, 'EUR');
    expect(valuation.currentValueInBaseCurrency, 240);
    expect(valuation.historicalCostBasisInBaseCurrency, 200);
    expect(valuation.profitLossInBaseCurrency, 40);
    expect(valuation.profitLossPercentage, 20);
    expect(valuation.fxEvidence, isEmpty);
  });

  test('converts current USD value to EUR but blocks historical P/L', () async {
    final service = PortfolioCurrentValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        expect(baseCurrency, 'USD');
        expect(quoteCurrency, 'EUR');
        return usdEur(rate: 0.85);
      },
    );

    final valuation = await service.value(
      positions: [
        position(
          symbol: 'MSFT',
          currency: 'USD',
          shares: 2,
          averagePrice: 100,
          currentPrice: 120,
        ),
      ],
    );

    expect(valuation.currentValueInBaseCurrency, 204);
    expect(valuation.positionsValued, 1);
    expect(valuation.fxEvidence, hasLength(1));
    expect(valuation.historicalCostBasisInBaseCurrency, isNull);
    expect(valuation.profitLossInBaseCurrency, isNull);
    expect(valuation.profitLossPercentage, isNull);
  });

  test('reuses one FX quote for positions sharing the same currency', () async {
    var fxCalls = 0;
    final service = PortfolioCurrentValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        fxCalls += 1;
        return usdEur(rate: 0.5);
      },
    );

    final valuation = await service.value(
      positions: [
        position(symbol: 'A', currency: 'USD', shares: 1, currentPrice: 100),
        position(symbol: 'B', currency: 'USD', shares: 1, currentPrice: 50),
      ],
    );

    expect(fxCalls, 1);
    expect(valuation.currentValueInBaseCurrency, 75);
    expect(valuation.fxEvidence, hasLength(1));
    expect(valuation.hasHistoricalCostBasis, isFalse);
  });

  test('fails closed when a position has no verifiable currency', () async {
    final service = PortfolioCurrentValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        return usdEur();
      },
    );

    final invalid = PortfolioPosition(
      symbol: 'LEGACY',
      companyName: 'Legacy',
      shares: 1,
      averagePrice: 100,
      currentPrice: 120,
      priceCurrency: null,
    );

    expect(
      () => service.value(positions: [invalid]),
      throwsStateError,
    );
  });

  test('rejects FX evidence for a different currency pair', () async {
    final observedAt = DateTime.utc(2026, 9, 3, 0, 0);
    final wrongPair = FxQuote(
      status: 'ok',
      baseCurrency: 'GBP',
      quoteCurrency: 'EUR',
      rate: 1.1,
      observedAt: observedAt,
      retrievedAt: observedAt.add(const Duration(seconds: 1)),
      sourceProvider: 'yahoo',
      sourceSymbol: 'GBPEUR=X',
      historicalPointInTimeEligible: false,
    );
    final service = PortfolioCurrentValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        return wrongPair;
      },
    );

    expect(
      () => service.value(
        positions: [position(symbol: 'MSFT', currency: 'USD')],
      ),
      throwsStateError,
    );
  });
}
