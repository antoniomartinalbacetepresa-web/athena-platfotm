import '../models/recommendation_learning_status.dart';

abstract class RecommendationLearningStatusProvider {
  Future<RecommendationLearningStatus> getStatus({
    DateTime? asOf,
    String? modelVersion,
    int? horizonDays,
  });
}
