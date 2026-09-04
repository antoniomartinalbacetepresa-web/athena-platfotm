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
      shadowLiveLongitudinal: const {
        'persistedCandidateCount': 8,
        'eligibleCandidateCount': 7,
        'evaluatedCandidateCount': 5,
        'evaluatedObservationCount': 12,
      },
      advisoryStatus: 'no_advice',
      productionEligible: false,
      automaticModelMutation: false,
      automaticProductionPromotion: false,
      automaticTrading: false,
    );
  }
}

void main() {
  testWidgets(
    'muestra aprendizaje shadow real sin recomendaciones ficticias',
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
      expect(find.text('APRENDIZAJE SHADOW'), findsOneWidget);
      expect(
        find.text(
          'ATHENA ya está midiendo candidatos con resultados reales.',
        ),
        findsOneWidget,
      );
      expect(find.text('Candidatos shadow'), findsOneWidget);
      expect(find.text('Candidatos evaluados'), findsOneWidget);
      expect(find.text('Observaciones maduras'), findsOneWidget);
      expect(find.text('Evaluaciones pendientes'), findsOneWidget);
      expect(find.text('8'), findsOneWidget);
      expect(find.text('5'), findsOneWidget);
      expect(find.text('12'), findsOneWidget);
      expect(find.text('4'), findsOneWidget);

      expect(find.text('Microsoft'), findsNothing);
      expect(find.text('Apple'), findsNothing);
      expect(find.text('NVIDIA'), findsNothing);
      expect(find.text('COMPRAR'), findsNothing);
      expect(find.text('MOTOR EN VALIDACIÓN'), findsNothing);
    },
  );
}
