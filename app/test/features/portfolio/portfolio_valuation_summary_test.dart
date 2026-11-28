import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/portfolio/models/portfolio_valuation_summary.dart';
import 'package:app/features/portfolio/services/portfolio_current_valuation_service.dart';

PortfolioCurrentValuation valuation({
  required double currentValue,
  double? historicalCostBasis,
  bool usesFx = false,
}) {
  return PortfolioCurrentValuation(
    baseCurrency: 'EUR',
    currentValueInBaseCurrency: currentValue,
    positionsValued: 1,
    fxEvidence: usesFx
        ? [
            throw UnimplementedError('FX evidence is not needed by this test helper'),
          ]
        : const [],
    historicalCostBasisInBaseCurrency: historicalCostBasis,
    latestMarketObservedAt: DateTime.utc(2026, 9, 3, 7),
    latestMarketRetrievedAt: DateTime.utc(2026, 9, 3, 7, 1),
    latestFxObservedAt: usesFx ? DateTime.utc(2026, 9, 3, 7) : null,
    latestFxRetrievedAt: usesFx ? DateTime.utc(2026, 9, 3, 7, 1) : null,
  );
}

void main() {
  test('derives historical comparisons only from comparable cost basis', () {
    final summary = PortfolioValuationSummary.fromValuation(
      valuation: valuation(
        currentValue: 1200,
        historicalCostBasis: 1000,
      ),
      referenceCapital: 1500,
    );

    expect(summary.currentValue, 1200);
    expect(summary.investedCapital, 1000);
    expect(summary.profitLoss, 200);
    expect(summary.profitLossPercentage, 20);
    expect(summary.unallocatedCapital, 500);
    expect(summary.excessOverReference, 0);
    expect(summary.historicalComparisonsAvailable, isTrue);
  });

  test('does not infer historical metrics from current converted value', () {
    final summary = PortfolioValuationSummary.fromValuation(
      valuation: valuation(
        currentValue: 1200,
        historicalCostBasis: null,
      ),
      referenceCapital: 1500,
    );

    expect(summary.currentValue, 1200);
    expect(summary.investedCapital, isNull);
    expect(summary.profitLoss, isNull);
    expect(summary.profitLossPercentage, isNull);
    expect(summary.unallocatedCapital, isNull);
    expect(summary.excessOverReference, isNull);
    expect(summary.historicalComparisonsAvailable, isFalse);
  });

  test('reports excess over reference from historical cost basis', () {
    final summary = PortfolioValuationSummary.fromValuation(
      valuation: valuation(
        currentValue: 1800,
        historicalCostBasis: 1600,
      ),
      referenceCapital: 1500,
    );

    expect(summary.unallocatedCapital, 0);
    expect(summary.excessOverReference, 100);
  });

  test('rejects non-finite or negative reference capital', () {
    expect(
      () => PortfolioValuationSummary.fromValuation(
        valuation: valuation(currentValue: 1000, historicalCostBasis: 900),
        referenceCapital: double.nan,
      ),
      throwsStateError,
    );
    expect(
      () => PortfolioValuationSummary.fromValuation(
        valuation: valuation(currentValue: 1000, historicalCostBasis: 900),
        referenceCapital: -1,
      ),
      throwsStateError,
    );
  });
}
