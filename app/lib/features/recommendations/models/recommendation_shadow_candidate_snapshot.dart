class RecommendationShadowCandidateSnapshot {
  final String status;
  final DateTime asOf;
  final DateTime? candidateAsOf;
  final DateTime? persistedAt;
  final int? recordId;
  final RecommendationShadowCandidate? candidate;
  final String advisoryStatus;
  final bool recommendationCandidateReady;
  final bool productionEligible;
  final bool automaticTrading;

  const RecommendationShadowCandidateSnapshot({
    required this.status,
    required this.asOf,
    required this.candidateAsOf,
    required this.persistedAt,
    required this.recordId,
    required this.candidate,
    required this.advisoryStatus,
    required this.recommendationCandidateReady,
    required this.productionEligible,
    required this.automaticTrading,
  });

  bool get hasCandidate => candidate != null;

  bool get isShadowSafe =>
      advisoryStatus == 'no_advice' &&
      !recommendationCandidateReady &&
      !productionEligible &&
      !automaticTrading &&
      (candidate?.isShadowSafe ?? true);
}

class RecommendationShadowCandidate {
  final String symbol;
  final int? instrumentId;
  final DateTime asOf;
  final String candidateFingerprint;
  final Map<int, RecommendationShadowHorizon> horizons;
  final Map<String, dynamic> riskContext;
  final Map<String, dynamic> valuationContext;
  final Map<String, dynamic> fundamentalContext;
  final String advisoryStatus;
  final bool recommendationCandidateReady;
  final bool productionEligible;

  const RecommendationShadowCandidate({
    required this.symbol,
    required this.instrumentId,
    required this.asOf,
    required this.candidateFingerprint,
    required this.horizons,
    required this.riskContext,
    required this.valuationContext,
    required this.fundamentalContext,
    required this.advisoryStatus,
    required this.recommendationCandidateReady,
    required this.productionEligible,
  });

  bool get isShadowSafe =>
      advisoryStatus == 'no_advice' &&
      !recommendationCandidateReady &&
      !productionEligible;

  List<RecommendationShadowHorizon> get inferredHorizons {
    final values = horizons.values
        .where((item) => item.expectedExcessReturn != null)
        .toList(growable: false);
    values.sort((a, b) => a.horizonDays.compareTo(b.horizonDays));
    return values;
  }
}

class RecommendationShadowHorizon {
  final int horizonDays;
  final double? expectedExcessReturn;
  final String? modelFingerprint;
  final Map<String, dynamic> explanation;

  const RecommendationShadowHorizon({
    required this.horizonDays,
    required this.expectedExcessReturn,
    required this.modelFingerprint,
    required this.explanation,
  });
}
