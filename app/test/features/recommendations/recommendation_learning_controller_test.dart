import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/recommendations/controllers/recommendation_learning_controller.dart';
import 'package:app/features/recommendations/models/recommendation_learning_status.dart';
import 'package:app/features/recommendations/services/recommendation_learning_status_provider.dart';

class FakeRecommendationLearningStatusProvider
    implements RecommendationLearningStatusProvider {
  RecommendationLearningStatus? result;
  Object? error;
  int calls = 0;

  @override
  Future<RecommendationLearningStatus> getStatus({
    DateTime? asOf,
    String? modelVersion,
    int? horizonDays,
  }) async {
    calls += 1;
    if (error != null) {
      throw error!;
    }
    return result!;
  }
}

RecommendationLearningStatus _status() {
  return RecommendationLearningStatus(
    status: 'learning_diagnostics_only',
    asOf: DateTime.utc(2026, 9, 1, 20, 30),
    modelVersion: 'athena-v1',
    horizonDays: 90,
    performance: const {'sampleSize': 42},
    calibration: const {'status': 'review_required'},
    evaluationSchedule: const {'dueCount': 3},
    drift: const {'status': 'stable'},
    automaticModelMutation: false,
  );
}

void main() {
  test('carga y conserva el estado de aprendizaje', () async {
    final provider = FakeRecommendationLearningStatusProvider()
      ..result = _status();
    final controller = RecommendationLearningController(provider: provider);

    await controller.load(
      modelVersion: 'athena-v1',
      horizonDays: 90,
    );

    expect(provider.calls, 1);
    expect(controller.isLoading, isFalse);
    expect(controller.error, isNull);
    expect(controller.status?.performance['sampleSize'], 42);
  });

  test('expone error y elimina estado obsoleto si falla la carga', () async {
    final provider = FakeRecommendationLearningStatusProvider()
      ..result = _status();
    final controller = RecommendationLearningController(provider: provider);

    await controller.load();
    expect(controller.status, isNotNull);

    provider.error = Exception('backend unavailable');
    await controller.load();

    expect(controller.status, isNull);
    expect(controller.isLoading, isFalse);
    expect(controller.error, contains('backend unavailable'));
  });

  test('clear restablece el controlador', () async {
    final provider = FakeRecommendationLearningStatusProvider()
      ..result = _status();
    final controller = RecommendationLearningController(provider: provider);

    await controller.load();
    controller.clear();

    expect(controller.status, isNull);
    expect(controller.error, isNull);
    expect(controller.isLoading, isFalse);
  });
}
