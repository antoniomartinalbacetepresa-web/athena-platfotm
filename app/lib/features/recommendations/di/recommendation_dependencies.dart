import '../controllers/recommendation_learning_controller.dart';
import '../data/datasources/athena_backend_recommendation_learning_data_source.dart';
import '../data/datasources/athena_backend_recommendation_shadow_candidate_data_source.dart';

class RecommendationDependencies {
  static const String _defaultBackendUrl = String.fromEnvironment(
    'ATHENA_BACKEND_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );

  final AthenaBackendRecommendationLearningDataSource learningDataSource;
  final AthenaBackendRecommendationShadowCandidateDataSource shadowCandidateDataSource;
  final RecommendationLearningController learningController;

  RecommendationDependencies({
    required this.learningDataSource,
    required this.shadowCandidateDataSource,
    required this.learningController,
  });

  factory RecommendationDependencies.create({
    String? baseUrl,
  }) {
    final effectiveBaseUrl = (baseUrl ?? _defaultBackendUrl).trim();
    if (effectiveBaseUrl.isEmpty) {
      throw StateError('ATHENA_BACKEND_URL no está configurada.');
    }

    final learningDataSource = AthenaBackendRecommendationLearningDataSource(
      baseUrl: effectiveBaseUrl,
    );
    final shadowCandidateDataSource =
        AthenaBackendRecommendationShadowCandidateDataSource(
      baseUrl: effectiveBaseUrl,
    );

    return RecommendationDependencies(
      learningDataSource: learningDataSource,
      shadowCandidateDataSource: shadowCandidateDataSource,
      learningController: RecommendationLearningController(
        provider: learningDataSource,
      ),
    );
  }

  void dispose() {
    learningController.dispose();
    learningDataSource.dispose();
    shadowCandidateDataSource.dispose();
  }
}
