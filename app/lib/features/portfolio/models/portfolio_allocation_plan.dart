class PortfolioAllocationLine {
  final String symbol;
  final double targetWeight;
  final double targetAmount;
  final String sourceRecommendationId;
  final String evidenceFingerprint;

  const PortfolioAllocationLine({
    required this.symbol,
    required this.targetWeight,
    required this.targetAmount,
    required this.sourceRecommendationId,
    required this.evidenceFingerprint,
  });
}

class PortfolioAllocationPlan {
  final double referenceCapital;
  final List<PortfolioAllocationLine> lines;
  final double allocatedAmount;
  final double cashReserveAmount;
  final double cashReserveWeight;

  const PortfolioAllocationPlan({
    required this.referenceCapital,
    required this.lines,
    required this.allocatedAmount,
    required this.cashReserveAmount,
    required this.cashReserveWeight,
  });
}
