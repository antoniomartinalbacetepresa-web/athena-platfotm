import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/dashboard/presentation/widgets/recommendations_panel.dart';
import 'package:app/features/recommendations/models/recommendation_learning_status.dart';
import 'package:app/features/recommendations/models/recommendation_production_state.dart';
import 'package:app/features/recommendations/models/recommendation_shadow_candidate_snapshot.dart';
import 'package:app/features/recommendations/services/recommendation_learning_status_provider.dart';
import 'package:app/features/recommendations/services/recommendation_production_state_provider.dart';
import 'package:app/features/recommendations/services/recommendation_shadow_candidate_provider.dart';

const _candidateFingerprint =
    '1111111111111111111111111111111111111111111111111111111111111111';
const _recommendationFingerprint =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const _allocationFingerprint =
    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
const _economicFingerprint =
    'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc';

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
        candidateFingerprint: _candidateFingerprint,
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

class FakeProductionStateProvider implements RecommendationProductionStateProvider {
  final bool withRecommendation;
  final bool withAllocation;

  FakeProductionStateProvider({
    this.withRecommendation = false,
    this.withAllocation = false,
  });

  @override
  Future<RecommendationProductionState> getLatest({
    DateTime? asOf,
    String? symbol,
    int? instrumentId,
  }) async {
    final cutoff = DateTime.utc(2026, 9, 1, 20, 30);
    if (!withRecommendation) {
      return RecommendationProductionState(
        asOf: cutoff,
        recommendation: null,
        allocation: null,
        productionRecommendationAvailable: false,
        productionAllocationAvailable: false,
        automaticTrading: false,
        readOnly: true,
      );
    }
    final recommendation = RecommendationProductionRecommendation(
      instrumentId: 7,
      symbol: 'AAPL',
      action: 'buy',
      policyState: 'flat',
      asOf: DateTime.utc(2026, 9, 1, 20),
      authorizedAt: DateTime.utc(2026, 9, 1, 20, 10),
      authorizationFingerprint: _recommendationFingerprint,
      economicContractFingerprint: _economicFingerprint,
    );
    final allocation = withAllocation
        ? RecommendationProductionAllocation(
            instrumentId: 7,
            symbol: 'AAPL',
            action: 'buy',
            asOf: DateTime.utc(2026, 9, 1, 20),
            authorizedAt: DateTime.utc(2026, 9, 1, 20, 15),
            authorizationFingerprint: _allocationFingerprint,
            recommendationAuthorizationFingerprint: _recommendationFingerprint,
            economicContractFingerprint: _economicFingerprint,
            baseCurrency: 'EUR',
            referenceCapital: 10000,
            targetAmountInBaseCurrency: 1500,
            deltaAmountInBaseCurrency: 1500,
          )
        : null;
    return RecommendationProductionState(
      asOf: cutoff,
      recommendation: recommendation,
      allocation: allocation,
      productionRecommendationAvailable: true,
      productionAllocationAvailable: allocation != null,
      automaticTrading: false,
      readOnly: true,
    );
  }
}

Widget _panel({
  bool withShadow = true,
  bool withProduction = false,
  bool withAllocation = false,
}) {
  return MaterialApp(
    home: Scaffold(
      body: SizedBox(
        width: 900,
        height: 650,
        child: RecommendationsPanel(
          learningStatusProvider: FakeLearningStatusProvider(),
          shadowCandidateProvider: FakeShadowCandidateProvider(
            withCandidate: withShadow,
          ),
          productionStateProvider: FakeProductionStateProvider(
            withRecommendation: withProduction,
            withAllocation: withAllocation,
          ),
        ),
      ),
    ),
  );
}

void main() {
  testWidgets(
    'muestra aprendizaje y candidato shadow real sin consejo ficticio',
    (tester) async {
      await tester.pumpWidget(_panel());
      await tester.pumpAndSettle();

      expect(find.text('RECOMENDACIONES ATHENA'), findsOneWidget);
      expect(find.text('APRENDIZAJE SHADOW'), findsOneWidget);
      expect(
        find.text('ATHENA ya está midiendo candidatos con resultados reales.'),
        findsOneWidget,
      );
      expect(
        find.text('No existe una recomendación productiva autorizada conocida por ATHENA.'),
        findsOneWidget,
      );
      expect(find.text('Candidato shadow verificable · AAPL'), findsOneWidget);
      expect(find.textContaining('30d: +1.50% exceso esperado'), findsOneWidget);
      expect(find.textContaining('technicalScore +1.00 pp'), findsOneWidget);
      expect(find.textContaining('No constituye una recomendación'), findsOneWidget);
      expect(find.text('Candidatos shadow'), findsOneWidget);
      expect(find.text('Candidatos evaluados'), findsOneWidget);
      expect(find.text('Observaciones maduras'), findsOneWidget);
      expect(find.text('Evaluaciones pendientes'), findsOneWidget);

      expect(find.text('Microsoft'), findsNothing);
      expect(find.text('NVIDIA'), findsNothing);
      expect(find.text('COMPRAR'), findsNothing);
    },
  );

  testWidgets('muestra ausencia verificable sin inventar candidato ni recomendación',
      (tester) async {
    await tester.pumpWidget(_panel(withShadow: false));
    await tester.pumpAndSettle();

    expect(
      find.text(
        'Todavía no existe un candidato shadow verificable conocido por ATHENA.',
      ),
      findsOneWidget,
    );
    expect(
      find.text('No existe una recomendación productiva autorizada conocida por ATHENA.'),
      findsOneWidget,
    );
    expect(find.textContaining('exceso esperado'), findsNothing);
    expect(find.text('COMPRAR'), findsNothing);
  });

  testWidgets('muestra sólo la recomendación productiva autorizada y trazable',
      (tester) async {
    await tester.pumpWidget(_panel(withProduction: true));
    await tester.pumpAndSettle();

    expect(find.text('PRODUCTIVO AUTORIZADO'), findsOneWidget);
    expect(find.text('COMPRAR · AAPL'), findsOneWidget);
    expect(find.textContaining('Autorización productiva verificada'), findsOneWidget);
    expect(find.text('Estado de cartera: flat'), findsOneWidget);
    expect(
      find.text('No habilita ejecución de órdenes ni trading automático.'),
      findsOneWidget,
    );
    expect(find.textContaining('Asignación autorizada:'), findsNothing);
  });

  testWidgets('muestra allocation sólo cuando existe autorización separada',
      (tester) async {
    await tester.pumpWidget(
      _panel(withProduction: true, withAllocation: true),
    );
    await tester.pumpAndSettle();

    expect(find.text('PRODUCTIVO AUTORIZADO'), findsOneWidget);
    expect(find.textContaining('Asignación autorizada: 1500.00 EUR'), findsOneWidget);
    expect(find.textContaining('sobre 10000.00 EUR de referencia'), findsOneWidget);
    expect(find.textContaining('cambio +1500.00 EUR'), findsOneWidget);
    expect(
      find.textContaining('Ejecución automática deshabilitada'),
      findsOneWidget,
    );
  });
}
