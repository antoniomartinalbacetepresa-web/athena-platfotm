import 'package:app/features/recommendations/models/recommendation_allocation_request_context.dart';
import 'package:app/features/recommendations/models/recommendation_shadow_candidate_snapshot.dart';
import 'package:flutter_test/flutter_test.dart';

const _candidateFingerprint =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

RecommendationShadowCandidateSnapshot _snapshot({
  int? instrumentId = 7,
  DateTime? candidateAsOf,
  Map<int, RecommendationShadowHorizon>? horizons,
  String advisoryStatus = 'no_advice',
  bool recommendationCandidateReady = false,
  bool productionEligible = false,
  bool automaticTrading = false,
}) {
  final asOf = candidateAsOf ?? DateTime.utc(2026, 9, 1, 12);
  return RecommendationShadowCandidateSnapshot(
    status: 'shadow_candidate_available',
    asOf: asOf.add(const Duration(minutes: 1)),
    candidateAsOf: asOf,
    persistedAt: asOf.add(const Duration(seconds: 30)),
    recordId: 1,
    candidate: RecommendationShadowCandidate(
      symbol: 'TEST',
      instrumentId: instrumentId,
      asOf: asOf,
      candidateFingerprint: _candidateFingerprint,
      horizons: horizons ??
          const {
            30: RecommendationShadowHorizon(
              horizonDays: 30,
              expectedExcessReturn: null,
              modelFingerprint: null,
              explanation: {},
            ),
          },
      riskContext: const {},
      valuationContext: const {},
      fundamentalContext: const {},
      advisoryStatus: advisoryStatus,
      recommendationCandidateReady: recommendationCandidateReady,
      productionEligible: productionEligible,
    ),
    advisoryStatus: advisoryStatus,
    recommendationCandidateReady: recommendationCandidateReady,
    productionEligible: productionEligible,
    automaticTrading: automaticTrading,
  );
}

void main() {
  test('shadow evidence can provide context but never allocation authority', () {
    final requestAsOf = DateTime.utc(2026, 9, 2, 12);

    final context = RecommendationAllocationRequestContext.fromShadowSnapshot(
      snapshot: _snapshot(),
      horizonDays: 30,
      requestAsOf: requestAsOf,
    );

    expect(context.instrumentId, 7);
    expect(context.horizonDays, 30);
    expect(context.candidateAsOf, DateTime.utc(2026, 9, 1, 12));
    expect(context.requestAsOf, requestAsOf);
    expect(context.shadowCandidateFingerprint, _candidateFingerprint);
  });

  test('horizon absent from the shadow candidate fails closed', () {
    expect(
      () => RecommendationAllocationRequestContext.fromShadowSnapshot(
        snapshot: _snapshot(),
        horizonDays: 90,
        requestAsOf: DateTime.utc(2026, 9, 2),
      ),
      throwsStateError,
    );
  });

  test('candidate after the requested PIT cutoff fails closed', () {
    expect(
      () => RecommendationAllocationRequestContext.fromShadowSnapshot(
        snapshot: _snapshot(candidateAsOf: DateTime.utc(2026, 9, 3)),
        horizonDays: 30,
        requestAsOf: DateTime.utc(2026, 9, 2),
      ),
      throwsStateError,
    );
  });

  test('non-shadow or canonically unidentified candidates cannot hand off', () {
    expect(
      () => RecommendationAllocationRequestContext.fromShadowSnapshot(
        snapshot: _snapshot(productionEligible: true),
        horizonDays: 30,
        requestAsOf: DateTime.utc(2026, 9, 2),
      ),
      throwsStateError,
    );

    expect(
      () => RecommendationAllocationRequestContext.fromShadowSnapshot(
        snapshot: _snapshot(instrumentId: null),
        horizonDays: 30,
        requestAsOf: DateTime.utc(2026, 9, 2),
      ),
      throwsStateError,
    );
  });
}
