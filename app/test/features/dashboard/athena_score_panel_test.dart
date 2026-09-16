import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/dashboard/presentation/widgets/athena_score_panel.dart';
import 'package:app/features/recommendations/models/recommendation_learning_status.dart';
import 'package:app/features/recommendations/services/recommendation_learning_status_provider.dart';

class FakeLearningStatusProvider implements RecommendationLearningStatusProvider {
  @override
  Future<RecommendationLearningStatus> getStatus({
    DateTime? asOf,
    String? modelVersion,
    int? horizonDays,
  }) async {
    return RecommendationLearningStatus(
      status: 'learning_diagnostics_only',
      asOf: DateTime.utc(2026, 9, 2, 16),
      modelVersion: null,
      horizonDays: null,
      performance: const {'sampleCount': 21},
      calibration: const {'status': 'review_required'},
      evaluationSchedule: const {'dueCount': 5},
      drift: const {'status': 'stable'},
      automaticModelMutation: false,
    );
  }
}

void main() {
  testWidgets(
    'muestra estado real de aprendizaje sin fabricar un score de producción',
    (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 420,
              height: 520,
              child: AthenaScorePanel(
                learningStatusProvider: FakeLearningStatusProvider(),
              ),
            ),
          ),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.text('ATHENA SCORE'), findsOneWidget);
      expect(find.text('SIN CALIFICAR'), findsOneWidget);
      expect(find.text('21'), findsOneWidget);
      expect(find.text('5'), findsOneWidget);
      expect(find.text('STABLE'), findsOneWidget);
      expect(find.text('BLOQUEADA'), findsOneWidget);
      expect(find.text('92'), findsNothing);
      expect(find.text('Excelente'), findsNothing);
      expect(find.text('Potencial'), findsNothing);
      expect(find.text('Alto'), findsNothing);
    },
  );
}
