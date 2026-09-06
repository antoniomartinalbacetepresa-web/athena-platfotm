import 'package:app/features/portfolio/data/athena_backend_portfolio_allocation_authority_data_source.dart';
import 'package:app/features/portfolio/data/athena_backend_portfolio_allocation_data_source.dart';
import 'package:app/features/portfolio/models/portfolio_position.dart';
import 'package:app/features/portfolio/presentation/controllers/portfolio_allocation_controller.dart';
import 'package:app/features/recommendations/models/recommendation_allocation_request_context.dart';
import 'package:app/features/recommendations/models/recommendation_shadow_candidate_snapshot.dart';
import 'package:flutter_test/flutter_test.dart';

const _actionFingerprint =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const _economicFingerprint =
    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
const _correlationFingerprint =
    'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc';
const _valuationFingerprint =
    'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd';
const _allocationFingerprint =
    'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee';
const _pipelineFingerprint =
    'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff';

class _FakeAuthorityDataSource
    extends AthenaBackendPortfolioAllocationAuthorityDataSource {
  final AthenaBackendPortfolioAllocationAuthorityResolution resolution;
  int calls = 0;
  int? receivedInstrumentId;
  int? receivedHorizonDays;
  DateTime? receivedAsOf;
  List<int>? receivedHeldInstrumentIds;

  _FakeAuthorityDataSource(this.resolution) : super(baseUrl: 'http://localhost');

  @override
  Future<AthenaBackendPortfolioAllocationAuthorityResolution> resolve({
    required int instrumentId,
    required int horizonDays,
    required List<int> heldInstrumentIds,
    required DateTime asOf,
  }) async {
    calls += 1;
    receivedInstrumentId = instrumentId;
    receivedHorizonDays = horizonDays;
    receivedAsOf = asOf.toUtc();
    receivedHeldInstrumentIds = List<int>.from(heldInstrumentIds);
    return resolution;
  }
}

class _FakeAllocationDataSource extends AthenaBackendPortfolioAllocationDataSource {
  int calls = 0;
  String? receivedActionFingerprint;
  List<String>? receivedCorrelationFingerprints;

  _FakeAllocationDataSource() : super(baseUrl: 'http://localhost');

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
    receivedActionFingerprint = uncertaintyBoundActionCandidateFingerprint;
    receivedCorrelationFingerprints =
        List<String>.from(correlationEvidenceFingerprints);
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
      correlationEvidenceFingerprints: const [_correlationFingerprint],
    );
  }
}

RecommendationAllocationRequestContext _recommendationContext(DateTime requestAsOf) {
  final candidateAsOf = requestAsOf.subtract(const Duration(hours: 1));
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
    requestAsOf: requestAsOf,
  );
}

void main() {
  final cutoff = DateTime.utc(2026, 9, 1, 12);

  test('not-ready authority blocks allocation without fallback', () async {
    final authority = _FakeAuthorityDataSource(
      AthenaBackendPortfolioAllocationAuthorityResolution(
        asOf: cutoff,
        instrumentId: 7,
        horizonDays: 30,
        ready: false,
        reason: 'validated_oos_evidence_not_ready',
        actionCandidateFingerprint: null,
        correlationEvidenceFingerprints: const [],
      ),
    );
    final allocation = _FakeAllocationDataSource();
    final controller = PortfolioAllocationController(
      authorityDataSource: authority,
      allocationDataSource: allocation,
    );

    await controller.load(
      instrumentId: 7,
      horizonDays: 30,
      allocationPolicyId: 'default-long-only',
      referenceCapital: 100,
      baseCurrency: 'EUR',
      positions: const [],
      asOf: cutoff,
    );

    expect(authority.calls, 1);
    expect(allocation.calls, 0);
    expect(controller.candidate, isNull);
    expect(controller.error, isNull);
    expect(controller.blockedReason, 'validated_oos_evidence_not_ready');
    expect(controller.isReady, isFalse);
  });

  test('resolved backend authorities are the only fingerprints sent to allocation',
      () async {
    final authority = _FakeAuthorityDataSource(
      AthenaBackendPortfolioAllocationAuthorityResolution(
        asOf: cutoff,
        instrumentId: 7,
        horizonDays: 30,
        ready: true,
        reason: null,
        actionCandidateFingerprint: _actionFingerprint,
        correlationEvidenceFingerprints: const [_correlationFingerprint],
      ),
    );
    final allocation = _FakeAllocationDataSource();
    final controller = PortfolioAllocationController(
      authorityDataSource: authority,
      allocationDataSource: allocation,
    );

    await controller.load(
      instrumentId: 7,
      horizonDays: 30,
      allocationPolicyId: 'default-long-only',
      referenceCapital: 100,
      baseCurrency: 'eur',
      positions: const [],
      asOf: cutoff,
    );

    expect(authority.receivedHeldInstrumentIds, isEmpty);
    expect(allocation.calls, 1);
    expect(allocation.receivedActionFingerprint, _actionFingerprint);
    expect(
      allocation.receivedCorrelationFingerprints,
      const [_correlationFingerprint],
    );
    expect(controller.error, isNull);
    expect(controller.blockedReason, isNull);
    expect(controller.isReady, isTrue);
    expect(controller.candidate?.economicContractFingerprint, _economicFingerprint);
  });

  test('recommendation context forwards only instrument horizon and PIT cutoff',
      () async {
    final authority = _FakeAuthorityDataSource(
      AthenaBackendPortfolioAllocationAuthorityResolution(
        asOf: cutoff,
        instrumentId: 7,
        horizonDays: 30,
        ready: false,
        reason: 'validated_oos_evidence_not_ready',
        actionCandidateFingerprint: null,
        correlationEvidenceFingerprints: const [],
      ),
    );
    final allocation = _FakeAllocationDataSource();
    final controller = PortfolioAllocationController(
      authorityDataSource: authority,
      allocationDataSource: allocation,
    );

    await controller.loadFromRecommendationContext(
      context: _recommendationContext(cutoff),
      allocationPolicyId: 'default-long-only',
      referenceCapital: 100,
      baseCurrency: 'EUR',
      positions: const [],
    );

    expect(authority.calls, 1);
    expect(authority.receivedInstrumentId, 7);
    expect(authority.receivedHorizonDays, 30);
    expect(authority.receivedAsOf, cutoff);
    expect(allocation.calls, 0);
    expect(controller.blockedReason, 'validated_oos_evidence_not_ready');
  });

  test('non-finite reference capital fails closed before backend calls', () async {
    final authority = _FakeAuthorityDataSource(
      AthenaBackendPortfolioAllocationAuthorityResolution(
        asOf: cutoff,
        instrumentId: 7,
        horizonDays: 30,
        ready: true,
        reason: null,
        actionCandidateFingerprint: _actionFingerprint,
        correlationEvidenceFingerprints: const [],
      ),
    );
    final allocation = _FakeAllocationDataSource();
    final controller = PortfolioAllocationController(
      authorityDataSource: authority,
      allocationDataSource: allocation,
    );

    await controller.load(
      instrumentId: 7,
      horizonDays: 30,
      allocationPolicyId: 'default-long-only',
      referenceCapital: double.nan,
      baseCurrency: 'EUR',
      positions: const [],
      asOf: cutoff,
    );

    expect(authority.calls, 0);
    expect(allocation.calls, 0);
    expect(controller.candidate, isNull);
    expect(controller.error, isNotNull);
    expect(controller.isReady, isFalse);
  });
}
