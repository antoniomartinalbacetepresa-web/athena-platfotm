class RecommendationLearningStatus {
  final String status;
  final DateTime asOf;
  final String? modelVersion;
  final int? horizonDays;
  final Map<String, dynamic> performance;
  final Map<String, dynamic> calibration;
  final Map<String, dynamic> evaluationSchedule;
  final Map<String, dynamic>? drift;
  final bool automaticModelMutation;

  const RecommendationLearningStatus({
    required this.status,
    required this.asOf,
    required this.modelVersion,
    required this.horizonDays,
    required this.performance,
    required this.calibration,
    required this.evaluationSchedule,
    required this.drift,
    required this.automaticModelMutation,
  });

  bool get isDiagnosticOnly => status == 'learning_diagnostics_only';

  bool get requiresHumanReview => !automaticModelMutation;
}
