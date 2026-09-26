import '../controllers/athena_synthesis_controller.dart';
import '../controllers/recommendation_learning_controller.dart';
import '../data/datasources/athena_backend_professional_dossier_data_source.dart';
import '../data/datasources/athena_backend_recommendation_learning_data_source.dart';
import '../data/datasources/athena_backend_recommendation_production_data_source.dart';
import '../data/datasources/athena_backend_recommendation_shadow_candidate_data_source.dart';
import '../data/datasources/athena_backend_synthesis_data_source.dart';

class RecommendationDependencies {
  static const String _defaultBackendUrl = String.fromEnvironment(
    'ATHENA_BACKEND_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );

  final AthenaBackendRecommendationLearningDataSource learningDataSource;
  final AthenaBackendRecommendationShadowCandidateDataSource shadowCandidateDataSource;
  final AthenaBackendRecommendationProductionDataSource productionDataSource;
  final AthenaBackendProfessionalDossierDataSource professionalDossierDataSource;
  final AthenaBackendSynthesisDataSource synthesisDataSource;
  final RecommendationLearningController learningController;
  final AthenaSynthesisController synthesisController;

  RecommendationDependencies({
    required this.learningDataSource,
    required this.shadowCandidateDataSource,
    required this.productionDataSource,
    required this.professionalDossierDataSource,
    required this.synthesisDataSource,
    required this.learningController,
    required this.synthesisController,
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
    final productionDataSource = AthenaBackendRecommendationProductionDataSource(
      baseUrl: effectiveBaseUrl,
    );
    final professionalDossierDataSource = AthenaBackendProfessionalDossierDataSource(
      baseUrl: effectiveBaseUrl,
    );
    final synthesisDataSource = AthenaBackendSynthesisDataSource(
      baseUrl: effectiveBaseUrl,
    );

    return RecommendationDependencies(
      learningDataSource: learningDataSource,
      shadowCandidateDataSource: shadowCandidateDataSource,
      productionDataSource: productionDataSource,
      professionalDossierDataSource: professionalDossierDataSource,
      synthesisDataSource: synthesisDataSource,
      learningController: RecommendationLearningController(
        provider: learningDataSource,
      ),
      synthesisController: AthenaSynthesisController(
        dataSource: synthesisDataSource,
      ),
    );
  }

  void dispose() {
    synthesisController.dispose();
    learningController.dispose();
    synthesisDataSource.dispose();
    learningDataSource.dispose();
    shadowCandidateDataSource.dispose();
    productionDataSource.dispose();
    professionalDossierDataSource.dispose();
  }
}
