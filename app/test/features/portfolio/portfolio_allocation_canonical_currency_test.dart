import 'package:app/features/portfolio/data/athena_backend_portfolio_allocation_authority_data_source.dart';
import 'package:app/features/portfolio/data/athena_backend_portfolio_allocation_data_source.dart';
import 'package:app/features/portfolio/models/portfolio_allocation_policy.dart';
import 'package:app/features/portfolio/models/portfolio_position.dart';
import 'package:app/features/portfolio/presentation/controllers/portfolio_allocation_controller.dart';
import 'package:app/features/recommendations/models/recommendation_allocation_request_context.dart';
import 'package:app/features/recommendations/models/recommendation_shadow_candidate_snapshot.dart';
import 'package:flutter_test/flutter_test.dart';

const _shaA =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const _shaB =
    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
const _shaC =
    'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc';
const _shaD =
    'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd';
const _shaE =
    'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee';

class _Authority extends AthenaBackendPortfolioAllocationAuthorityDataSource {
  int calls = 0;

  _Authority() : super(baseUrl: 'http://localhost');

  @override
  Future<AthenaBackendPortfolioAllocationAuthorityResolution> resolve({
    required int instrumentId,
    required int horizonDays,
    required List<int> heldInstrumentIds,
    required DateTime asOf,
  }) async {
    calls += 1;
    return AthenaBackendPortfolioAllocationAuthorityResolution(
      asOf: asOf.toUtc(),
      instrumentId: instrumentId,
      horizonDays: horizonDays,
      ready: true,
      reason: null,
      actionCandidateFingerprint: _shaA,
      correlationEvidenceFingerprints: const [],
    );
  }
}

class _Allocation extends AthenaBackendPortfolioAllocationDataSource {
  int calls = 0;
  double? referenceCapital;
  String? baseCurrency;

  _Allocation() : super(baseUrl: 'http://localhost');

  @override
  Future<AthenaBackendPortfolioAllocationCandidate> buildAuthorizedCandidate({
    required String uncertaintyBoundActionCandidateFingerprint,
    required String allocationPolicyId,
    required double referenceCapital,
    required String baseCurrency,
    required List<PortfolioPosition> positions,
    required List<String> correlationEvidenceFingerprints,
    required DateTime asOf,
  }) async {
    calls += 1;
    this.referenceCapital = referenceCapital;
    this.baseCurrency = baseCurrency;
    return AthenaBackendPortfolioAllocationCandidate(
      asOf: asOf.toUtc(),
      baseCurrency: baseCurrency,
      instrumentId: 7,
      action: 'hold',
      policyState: 'flat',
      referenceCapital: referenceCapital,
      investedPositionsValueInBaseCurrency: 0,
      currentPositionValueInBaseCurrency: 0,
      excessOverReferenceCapital: 0,
      shortfallVsReferenceCapital: referenceCapital,
      targetWeight: 0,
      targetAmountInBaseCurrency: 0,
      deltaAmountInBaseCurrency: 0,
      increasesExposure: false,
      actionCandidateFingerprint: _shaA,
      economicContractFingerprint: _shaB,
      valuationFingerprint: _shaC,
      allocationCandidateFingerprint: _shaD,
      verifiedPipelineFingerprint: _shaE,
      correlationEvidenceFingerprints: const [],
    );
  }
}

PortfolioAllocationPolicy _policy(String currency) => PortfolioAllocationPolicy(
      policyId: 'verified-policy',
      baseCurrency: currency,
      maximumInstrumentSleeveWeight: 0.20,
      minimumCashReserveWeight: 0.10,
      maximumAbsolutePairCorrelation: 0.80,
      minimumCorrelationSampleCount: 60,
      maximumCorrelationAgeSeconds: 86400,
      registeredAt: DateTime.utc(2026, 9, 6, 12),
      policyFingerprint: _shaB,
    );

RecommendationAllocationRequestContext _context() {
  final candidateAsOf = DateTime.utc(2026, 9, 6, 12);
  final requestAsOf = candidateAsOf.add(const Duration(minutes: 5));
  final snapshot = RecommendationShadowCandidateSnapshot(
    status: 'shadow_candidate_available',
    asOf: candidateAsOf.add(const Duration(minutes: 1)),
    candidateAsOf: candidateAsOf,
    persistedAt: candidateAsOf.add(const Duration(seconds: 30)),
    recordId: 1,
    candidate: RecommendationShadowCandidate(
      symbol: 'TEST',
      instrumentId: 7,
      asOf: candidateAsOf,
      candidateFingerprint: _shaA,
      horizons: const {
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
      advisoryStatus: 'no_advice',
      recommendationCandidateReady: false,
      productionEligible: false,
    ),
    advisoryStatus: 'no_advice',
    recommendationCandidateReady: false,
    productionEligible: false,
    automaticTrading: false,
  );
  return RecommendationAllocationRequestContext.fromShadowSnapshot(
    snapshot: snapshot,
    horizonDays: 30,
    requestAsOf: requestAsOf,
  );
}

void main() {
  test('high-level allocation rejects policy currency other than canonical USD', () {
    final authority = _Authority();
    final allocation = _Allocation();
    final controller = PortfolioAllocationController(
      authorityDataSource: authority,
      allocationDataSource: allocation,
    );

    expect(
      () => controller.loadFromRecommendationContextWithPolicy(
        context: _context(),
        allocationPolicy: _policy('EUR'),
        referenceCapital: 11000,
        positions: const [],
      ),
      throwsStateError,
    );
    expect(authority.calls, 0);
    expect(allocation.calls, 0);
  });

  test('high-level allocation sends canonical USD amount unchanged', () async {
    final authority = _Authority();
    final allocation = _Allocation();
    final controller = PortfolioAllocationController(
      authorityDataSource: authority,
      allocationDataSource: allocation,
    );

    await controller.loadFromRecommendationContextWithPolicy(
      context: _context(),
      allocationPolicy: _policy('USD'),
      referenceCapital: 11000,
      positions: const [],
    );

    expect(authority.calls, 1);
    expect(allocation.calls, 1);
    expect(allocation.referenceCapital, 11000);
    expect(allocation.baseCurrency, 'USD');
    expect(controller.error, isNull);
    expect(controller.isReady, isTrue);
  });
}
