class RecommendationLearningStatus {
  final String status;
  final DateTime asOf;
  final String? modelVersion;
  final int? horizonDays;
  final Map<String, dynamic> performance;
  final Map<String, dynamic> calibration;
  final Map<String, dynamic> evaluationSchedule;
  final Map<String, dynamic>? drift;
  final Map<String, dynamic> shadowLiveLongitudinal;
  final String advisoryStatus;
  final bool productionEligible;
  final bool automaticModelMutation;
  final bool automaticProductionPromotion;
  final bool automaticTrading;

  const RecommendationLearningStatus({
    required this.status,
    required this.asOf,
    required this.modelVersion,
    required this.horizonDays,
    required this.performance,
    required this.calibration,
    required this.evaluationSchedule,
    required this.drift,
    required this.shadowLiveLongitudinal,
    required this.advisoryStatus,
    required this.productionEligible,
    required this.automaticModelMutation,
    required this.automaticProductionPromotion,
    required this.automaticTrading,
  });

  bool get isDiagnosticOnly => status == 'learning_diagnostics_only';

  bool get requiresHumanReview => !automaticModelMutation;

  bool get isShadowSafe =>
      advisoryStatus == 'no_advice' &&
      !productionEligible &&
      !automaticProductionPromotion &&
      !automaticTrading;

  int? get persistedShadowCandidateCount =>
      _nonNegativeInt(shadowLiveLongitudinal['persistedCandidateCount']);

  int? get eligibleShadowCandidateCount =>
      _nonNegativeInt(shadowLiveLongitudinal['eligibleCandidateCount']);

  int? get evaluatedShadowCandidateCount =>
      _nonNegativeInt(shadowLiveLongitudinal['evaluatedCandidateCount']);

  int? get evaluatedShadowObservationCount =>
      _nonNegativeInt(shadowLiveLongitudinal['evaluatedObservationCount']);

  bool get hasMatureShadowEvidence =>
      (evaluatedShadowObservationCount ?? 0) > 0;

  static int? _nonNegativeInt(dynamic value) {
    if (value is bool) {
      return null;
    }
    int? parsed;
    if (value is int) {
      parsed = value;
    } else if (value is num) {
      if (!value.isFinite || value != value.truncateToDouble()) {
        return null;
      }
      parsed = value.toInt();
    } else if (value is String) {
      parsed = int.tryParse(value.trim());
    }
    if (parsed == null || parsed < 0) {
      return null;
    }
    return parsed;
  }
}
