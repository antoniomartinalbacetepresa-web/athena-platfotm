import 'package:app/features/portfolio/data/athena_backend_portfolio_allocation_authority_data_source.dart';
import 'package:app/features/portfolio/data/athena_backend_portfolio_allocation_data_source.dart';
import 'package:app/features/portfolio/models/portfolio_allocation_policy.dart';
import 'package:app/features/portfolio/models/portfolio_position.dart';
import 'package:app/features/portfolio/presentation/controllers/portfolio_allocation_controller.dart';
import 'package:app/features/recommendations/models/recommendation_allocation_request_context.dart';
import 'package:app/features/recommendations/models/recommendation_shadow_candidate_snapshot.dart';
import 'package:flutter_test/flutter_test.dart';

const _actionFingerprint =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const _economicFingerprint =
    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
const _valuationFingerprint =
    'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc';
const _allocationFingerprint =
    'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd';
const _pipelineFingerprint =
    'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee';

class _AuthorityDataSource
    extends AthenaBackendPortfolioAllocationAuthorityDataSource {
  final DateTime cutoff;

  _AuthorityDataSource(this.cutoff) : super(baseUrl: 'http://localhost');

  @override
  Future<AthenaBackendPortfolioAllocationAuthorityResolution> resolve({
    required int instrumentId,
    required int horizonDays,
    required List<int> heldInstrumentIds,
    required DateTime asOf,
  }) async {
    return AthenaBackendPortfolioAllocationAuthorityResolution(
      asOf: cutoff,
      instrumentId: instrumentId,
      horizonDays: horizonDays,
      ready: true,
      reason: null,
      actionCandidateFingerprint: _actionFingerprint,
      correlationEvidenceFingerprints: const [],
    );
  }
}

class _AllocationDataSource extends AthenaBackendPortfolioAllocationDataSource {
  String? receivedPolicyId;
  String? receivedBaseCurrency;

  _AllocationDataSource() : super(baseUrl: 'http://localhost');

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
    receivedPolicyId = allocationPolicyId;
    receivedBaseCurrency = baseCurrency;
    return AthenaBackendPortfolioAllocationCandidate(
      asOf: asOf.toUtc(),
      baseCurrency: baseCurrency,
      instrumentId: 7,
      action: 'hold',
      policyState: 'full_long',
      referenceCapital: referenceCapital,
      investedPositionsValueInBaseCurrency: 80,
      currentPositionValueInBaseCurrency: 20,
      excessOverReferenceCapital: 0,
      shortfallVsReferenceCapital: 20,
      targetWeight: 0.2,
      targetAmountInBaseCurrency: 20,
      deltaAmountInBaseCurrency: 0,
      increasesExposure: false,
      actionCandidateFingerprint: _actionFingerprint,
      economicContractFingerprint: _economicFingerprint,
      valuationFingerprint: _valuationFingerprint,
      allocationCandidateFingerprint: _allocationFingerprint,
      verifiedPipelineFingerprint: _pipelineFingerprint,
      correlationEvidenceFingerprints: const [],
    );
  }
}

RecommendationAllocationRequestContext _context(DateTime cutoff) {
  final candidateAsOf = cutoff.subtract(const Duration(hours: 1));
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
      candidateFingerprint: _actionFingerprint,
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
    requestAsOf: cutoff,
  );
}

void main() {
  test('selected verified policy owns allocation policy ID and base currency',
      () async {
    final cutoff = DateTime.utc(2026, 9, 6, 12);
    final allocation = _AllocationDataSource();
    final controller = PortfolioAllocationController(
      authorityDataSource: _AuthorityDataSource(cutoff),
      allocationDataSource: allocation,
    );
    final selectedPolicy = PortfolioAllocationPolicy(
      policyId: 'explicit-eur-policy-v1',
      baseCurrency: 'EUR',
      maximumInstrumentSleeveWeight: 0.2,
      minimumCashReserveWeight: 0.1,
      maximumAbsolutePairCorrelation: 0.8,
      minimumCorrelationSampleCount: 60,
      maximumCorrelationAgeSeconds: 86400,
      registeredAt: DateTime.utc(2026, 9, 6, 10),
      policyFingerprint:
          'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff',
    );

    await controller.loadFromRecommendationContextWithPolicy(
      context: _context(cutoff),
      allocationPolicy: selectedPolicy,
      referenceCapital: 100,
      positions: const [],
    );

    expect(controller.error, isNull);
    expect(controller.isReady, isTrue);
    expect(allocation.receivedPolicyId, 'explicit-eur-policy-v1');
    expect(allocation.receivedBaseCurrency, 'EUR');
  });
}
