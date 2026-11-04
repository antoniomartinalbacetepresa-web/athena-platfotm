import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/portfolio/models/portfolio_position.dart';
import 'package:app/features/portfolio/services/portfolio_concentration_service.dart';
import 'package:app/features/portfolio/services/portfolio_current_valuation_service.dart';

PortfolioPosition position(String symbol) => PortfolioPosition(
      symbol: symbol,
      companyName: symbol,
      shares: 1,
      averagePrice: 100,
      currentPrice: 100,
      priceCurrency: 'USD',
      currentPriceUpdatedAt: DateTime.utc(2026, 9, 4, 15),
      currentPriceSourceProvider: 'ATHENA test evidence',
      currentPriceRetrievedAt: DateTime.utc(2026, 9, 4, 15, 1),
    );

PortfolioCurrentValuation valuation({
  required String baseCurrency,
  required double currentValue,
  int positionsValued = 1,
}) =>
    PortfolioCurrentValuation(
      baseCurrency: baseCurrency,
      currentValueInBaseCurrency: currentValue,
      positionsValued: positionsValued,
      fxEvidence: const [],
      historicalCostBasisInBaseCurrency: null,
      latestMarketObservedAt: DateTime.utc(2026, 9, 4, 15),
      latestMarketRetrievedAt: DateTime.utc(2026, 9, 4, 15, 1),
      latestFxObservedAt: null,
      latestFxRetrievedAt: null,
    );

void main() {
  test('computes descriptive concentration from verified base valuations', () async {
    final values = {'AAA': 75.0, 'BBB': 25.0};
    final service = PortfolioConcentrationService(
      loadValuation: ({required positions, required baseCurrency}) async {
        return valuation(
          baseCurrency: baseCurrency,
          currentValue: values[positions.single.symbol]!,
        );
      },
    );

    final result = await service.analyze(
      positions: [position('AAA'), position('BBB')],
      baseCurrency: 'eur',
    );

    expect(result.baseCurrency, 'EUR');
    expect(result.totalCurrentValue, 100);
    expect(result.positions[0].weight, 0.75);
    expect(result.positions[1].weight, 0.25);
    expect(result.concentrationIndex, closeTo(0.625, 1e-12));
    expect(result.effectivePositionCount, closeTo(1.6, 1e-12));
    expect(result.largestPositionSymbol, 'AAA');
    expect(result.largestPositionWeight, 0.75);
    expect(result.correlationAvailable, isFalse);
    expect(result.isAllocationReady, isFalse);
    expect(result.productionEligible, isFalse);
    expect(result.recommendationPolicy, 'no_advice');
  });

  test('uses verified valuation output instead of nominal position values', () async {
    final service = PortfolioConcentrationService(
      loadValuation: ({required positions, required baseCurrency}) async {
        final converted = positions.single.symbol == 'USD' ? 80.0 : 20.0;
        return valuation(baseCurrency: baseCurrency, currentValue: converted);
      },
    );

    final result = await service.analyze(
      positions: [position('USD'), position('EUR')],
    );

    expect(result.positions[0].weight, 0.8);
    expect(result.positions[1].weight, 0.2);
  });

  test('fails closed on duplicate symbols', () async {
    final service = PortfolioConcentrationService(
      loadValuation: ({required positions, required baseCurrency}) async =>
          valuation(baseCurrency: baseCurrency, currentValue: 100),
    );

    expect(
      () => service.analyze(positions: [position('AAA'), position('aaa')]),
      throwsStateError,
    );
  });

  test('fails closed when per-position valuation contract is inconsistent', () async {
    final service = PortfolioConcentrationService(
      loadValuation: ({required positions, required baseCurrency}) async =>
          valuation(
        baseCurrency: 'USD',
        currentValue: 100,
        positionsValued: 2,
      ),
    );

    expect(
      () => service.analyze(positions: [position('AAA')]),
      throwsStateError,
    );
  });

  test('rejects empty portfolio, invalid currency and non-finite value', () async {
    final service = PortfolioConcentrationService(
      loadValuation: ({required positions, required baseCurrency}) async =>
          valuation(baseCurrency: baseCurrency, currentValue: double.nan),
    );

    expect(() => service.analyze(positions: const []), throwsStateError);
    expect(
      () => service.analyze(positions: [position('AAA')], baseCurrency: 'EU'),
      throwsStateError,
    );
    expect(
      () => service.analyze(positions: [position('AAA')]),
      throwsStateError,
    );
  });
}
