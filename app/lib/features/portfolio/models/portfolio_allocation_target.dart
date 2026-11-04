class PortfolioAllocationTarget {
  final String symbol;
  final double targetWeight;
  final String sourceRecommendationId;
  final String evidenceFingerprint;
  final bool productionEligible;

  const PortfolioAllocationTarget({
    required this.symbol,
    required this.targetWeight,
    required this.sourceRecommendationId,
    required this.evidenceFingerprint,
    required this.productionEligible,
  });
}
