import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/dashboard/presentation/widgets/recommendations_panel.dart';
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
      asOf: DateTime.utc(2026, 9, 1, 20, 30),
      modelVersion: null,
      horizonDays: null,
      performance: const {'sampleCount': 12},
      calibration: const {'status': 'review_required'},
      evaluationSchedule: const {'dueCount': 4},
      drift: const {'status': 'stable'},
      automaticModelMutation: false,
    );
  }
}

void main() {
  testWidgets(
    'no muestra recomendaciones ficticias y expone el estado real del motor',
    (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 900,
              height: 500,
              child: RecommendationsPanel(
                learningStatusProvider: FakeLearningStatusProvider(),
              ),
            ),
          ),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.text('RECOMENDACIONES ATHENA'), findsOneWidget);
      expect(find.text('MOTOR EN VALIDACIÓN'), findsOneWidget);
      expect(
        find.text('ATHENA todavía no publica recomendaciones activas.'),
        findsOneWidget,
      );
      expect(find.text('12'), findsOneWidget);
      expect(find.text('4'), findsOneWidget);
      expect(find.text('STABLE'), findsOneWidget);
      expect(find.text('BLOQUEADOS'), findsOneWidget);

      expect(find.text('Microsoft'), findsNothing);
      expect(find.text('Apple'), findsNothing);
      expect(find.text('NVIDIA'), findsNothing);
      expect(find.text('COMPRAR'), findsNothing);
    },
  );
}
