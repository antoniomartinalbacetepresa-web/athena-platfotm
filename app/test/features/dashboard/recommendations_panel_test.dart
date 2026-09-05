import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/dashboard/presentation/widgets/recommendations_panel.dart';
import 'package:app/features/recommendations/models/recommendation_learning_status.dart';
import 'package:app/features/recommendations/models/recommendation_shadow_candidate_snapshot.dart';
import 'package:app/features/recommendations/services/recommendation_learning_status_provider.dart';
import 'package:app/features/recommendations/services/recommendation_shadow_candidate_provider.dart';

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

class FakeShadowCandidateProvider implements RecommendationShadowCandidateProvider {
  final bool withCandidate;

  FakeShadowCandidateProvider({this.withCandidate = true});

  @override
  Future<RecommendationShadowCandidateSnapshot> getLatest({DateTime? asOf}) async {
    final cutoff = DateTime.utc(2026, 9, 1, 20, 30);
    if (!withCandidate) {
      return RecommendationShadowCandidateSnapshot(
        status: 'no_shadow_candidate_known_at_cutoff',
        asOf: cutoff,
        candidateAsOf: null,
        persistedAt: null,
        recordId: null,
        candidate: null,
        advisoryStatus: 'no_advice',
        recommendationCandidateReady: false,
        productionEligible: false,
        automaticTrading: false,
      );
    }
    return RecommendationShadowCandidateSnapshot(
      status: 'shadow_candidate_available_non_advisory',
      asOf: cutoff,
      candidateAsOf: DateTime.utc(2026, 9, 1, 20),
      persistedAt: DateTime.utc(2026, 9, 1, 20, 5),
      recordId: 4,
      candidate: RecommendationShadowCandidate(
        symbol: 'AAPL',
        instrumentId: 7,
        asOf: DateTime.utc(2026, 9, 1, 20),
        candidateFingerprint: '1' * 64,
        horizons: const {
          30: RecommendationShadowHorizon(
            horizonDays: 30,
            expectedExcessReturn: 0.015,
            modelFingerprint: null,
            explanation: {
              'largestAbsoluteContributors': [
                {'feature': 'technicalScore', 'contribution': 0.01},
              ],
            },
          ),
        },
        riskContext: const {},
        valuationContext: const {},
        fundamentalContext: const {},
        advisoryStatus: 'no_advice',
        recommendationCandidateReady: false,
        productionEligible: false,
      ),
      advisoryStatus: 'no_advice',
      recommendationCandidateReady: false,
      productionEligible: false,
      automaticTrading: false,
    );
  }
}

void main() {
  testWidgets(
    'muestra aprendizaje y candidato shadow real sin consejo ficticio',
    (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 900,
              height: 650,
              child: RecommendationsPanel(
                learningStatusProvider: FakeLearningStatusProvider(),
                shadowCandidateProvider: FakeShadowCandidateProvider(),
              ),
            ),
          ),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.text('RECOMENDACIONES ATHENA'), findsOneWidget);
      expect(find.text('APRENDIZAJE SHADOW'), findsOneWidget);
      expect(
        find.text('ATHENA ya está midiendo candidatos con resultados reales.'),
        findsOneWidget,
      );
      expect(find.text('Candidato shadow verificable · AAPL'), findsOneWidget);
      expect(find.textContaining('30d: +1.50% exceso esperado'), findsOneWidget);
      expect(find.textContaining('technicalScore +1.00 pp'), findsOneWidget);
      expect(find.textContaining('No constituyen una recomendación'), findsOneWidget);
      expect(find.text('Candidatos shadow'), findsOneWidget);
      expect(find.text('Candidatos evaluados'), findsOneWidget);
      expect(find.text('Observaciones maduras'), findsOneWidget);
      expect(find.text('Evaluaciones pendientes'), findsOneWidget);

      expect(find.text('Microsoft'), findsNothing);
      expect(find.text('NVIDIA'), findsNothing);
      expect(find.text('COMPRAR'), findsNothing);
      expect(find.text('MOTOR EN VALIDACIÓN'), findsNothing);
    },
  );

  testWidgets('muestra ausencia verificable sin inventar candidato', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 900,
            height: 650,
            child: RecommendationsPanel(
              learningStatusProvider: FakeLearningStatusProvider(),
              shadowCandidateProvider: FakeShadowCandidateProvider(
                withCandidate: false,
              ),
            ),
          ),
        ),
      ),
    );

    await tester.pumpAndSettle();

    expect(
      find.text(
        'Todavía no existe un candidato shadow verificable conocido por ATHENA.',
      ),
      findsOneWidget,
    );
    expect(find.textContaining('exceso esperado'), findsNothing);
  });
}
