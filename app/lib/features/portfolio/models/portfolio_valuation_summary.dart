import '../services/portfolio_current_valuation_service.dart';

/// Presentation-safe monetary summary for a portfolio.
///
/// Current value may use current FX. Historical comparisons (invested capital,
/// P/L, return, unallocated capital and excess over reference) are exposed only
/// when [PortfolioCurrentValuation] contains a truthful historical cost basis in
/// the same base currency.
class PortfolioValuationSummary {
  final String baseCurrency;
  final double referenceCapital;
  final double currentValue;
  final double? investedCapital;
  final double? profitLoss;
  final double? profitLossPercentage;
  final double? unallocatedCapital;
  final double? excessOverReference;
  final bool usesCurrentFx;
  final DateTime? latestMarketObservedAt;
  final DateTime? latestMarketRetrievedAt;
  final DateTime? latestFxObservedAt;
  final DateTime? latestFxRetrievedAt;

  const PortfolioValuationSummary({
    required this.baseCurrency,
    required this.referenceCapital,
    required this.currentValue,
    required this.investedCapital,
    required this.profitLoss,
    required this.profitLossPercentage,
    required this.unallocatedCapital,
    required this.excessOverReference,
    required this.usesCurrentFx,
    required this.latestMarketObservedAt,
    required this.latestMarketRetrievedAt,
    required this.latestFxObservedAt,
    required this.latestFxRetrievedAt,
  });

  bool get hasReferenceCapital => referenceCapital > 0;

  bool get historicalComparisonsAvailable => investedCapital != null;

  factory PortfolioValuationSummary.fromValuation({
    required PortfolioCurrentValuation valuation,
    required double referenceCapital,
  }) {
    if (!referenceCapital.isFinite || referenceCapital < 0) {
      throw StateError('El capital de referencia no es finito o es negativo.');
    }
    if (!valuation.currentValueInBaseCurrency.isFinite ||
        valuation.currentValueInBaseCurrency < 0) {
      throw StateError('El valor actual agregado no es finito o es negativo.');
    }

    final invested = valuation.historicalCostBasisInBaseCurrency;
    if (invested != null && (!invested.isFinite || invested < 0)) {
      throw StateError('El coste histórico agregado no es finito o es negativo.');
    }

    final profitLoss = valuation.profitLossInBaseCurrency;
    final profitLossPercentage = valuation.profitLossPercentage;
    if (profitLoss != null && !profitLoss.isFinite) {
      throw StateError('El resultado agregado no es finito.');
    }
    if (profitLossPercentage != null && !profitLossPercentage.isFinite) {
      throw StateError('La rentabilidad agregada no es finita.');
    }

    double? unallocated;
    double? excess;
    if (referenceCapital > 0 && invested != null) {
      unallocated = (referenceCapital - invested).clamp(0.0, double.infinity);
      excess = (invested - referenceCapital).clamp(0.0, double.infinity);
    }

    return PortfolioValuationSummary(
      baseCurrency: valuation.baseCurrency,
      referenceCapital: referenceCapital,
      currentValue: valuation.currentValueInBaseCurrency,
      investedCapital: invested,
      profitLoss: profitLoss,
      profitLossPercentage: profitLossPercentage,
      unallocatedCapital: unallocated,
      excessOverReference: excess,
      usesCurrentFx: valuation.usesFx,
      latestMarketObservedAt: valuation.latestMarketObservedAt,
      latestMarketRetrievedAt: valuation.latestMarketRetrievedAt,
      latestFxObservedAt: valuation.latestFxObservedAt,
      latestFxRetrievedAt: valuation.latestFxRetrievedAt,
    );
  }
}
