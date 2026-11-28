class PortfolioConcentrationPosition {
  final String symbol;
  final double currentValueInBaseCurrency;
  final double weight;

  const PortfolioConcentrationPosition({
    required this.symbol,
    required this.currentValueInBaseCurrency,
    required this.weight,
  });
}

/// Descriptive concentration metrics derived only from verified current
/// valuations in one base currency.
///
/// These metrics do not classify risk, generate advice or unlock allocation.
/// Correlation remains unavailable until ATHENA can align verified historical
/// return series point-in-time for every relevant position.
class PortfolioConcentrationSnapshot {
  final String baseCurrency;
  final double totalCurrentValue;
  final List<PortfolioConcentrationPosition> positions;
  final double concentrationIndex;
  final double effectivePositionCount;
  final String largestPositionSymbol;
  final double largestPositionWeight;

  const PortfolioConcentrationSnapshot({
    required this.baseCurrency,
    required this.totalCurrentValue,
    required this.positions,
    required this.concentrationIndex,
    required this.effectivePositionCount,
    required this.largestPositionSymbol,
    required this.largestPositionWeight,
  });

  bool get correlationAvailable => false;
  bool get isAllocationReady => false;
  bool get productionEligible => false;
  String get recommendationPolicy => 'no_advice';
}
