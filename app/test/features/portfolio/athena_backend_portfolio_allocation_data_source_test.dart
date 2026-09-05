import 'dart:convert';

import 'package:app/features/portfolio/data/athena_backend_portfolio_allocation_data_source.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

const _fpA = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const _fpB = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
const _fpC = 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc';
const _fpD = 'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd';
const _fpE = 'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee';

Map<String, dynamic> _safeResponse() {
  return {
    'data': {
      'artifactVersion': 'athena-verified-allocation-pipeline-v3',
      'status': 'verified_allocation_pipeline_non_advisory',
      'asOf': '2026-09-05T12:00:00.000Z',
      'baseCurrency': 'EUR',
      'instrumentId': 7,
      'uncertaintyBoundActionCandidateFingerprint': _fpA,
      'portfolioValuationEvidenceFingerprint': _fpB,
      'allocationCandidateFingerprint': _fpC,
      'verifiedAllocationPipelineFingerprint': _fpD,
      'investedPositionsValueInBaseCurrency': 12500.0,
      'currentPositionValueInBaseCurrency': 2500.0,
      'actionAuthorityBoundToAllocation': true,
      'callerSuppliedActionArtifactsAccepted': false,
      'portfolioValuationBoundToAllocation': true,
      'portfolioValuationSealedBeforeAllocation': true,
      'callerSuppliedValuationTotalsAccepted': false,
      'correlationAuthorityBoundToAllocation': true,
      'callerSuppliedCorrelationArtifactsAccepted': false,
      'correlationAuthority': [
        {
          'evidenceFingerprint': _fpE,
          'recordFingerprint': _fpB,
          'persistedAt': '2026-09-05T12:01:00Z',
          'leftInstrumentId': 7,
          'rightInstrumentId': 9,
        },
      ],
      'advisoryStatus': 'no_advice',
      'recommendationCandidateReady': false,
      'productionEligible': false,
      'allocationEligible': false,
      'automaticTrading': false,
      'allocationCandidate': {
        'status': 'allocation_candidate_non_advisory',
        'asOf': '2026-09-05T12:00:00.000Z',
        'baseCurrency': 'EUR',
        'uncertaintyBoundActionCandidateFingerprint': _fpA,
        'action': 'hold',
        'policyState': 'full_long',
        'referenceCapital': 10000.0,
        'excessOverReferenceCapital': 2500.0,
        'shortfallVsReferenceCapital': 0.0,
        'targetWeight': 0.25,
        'targetAmountInBaseCurrency': 2500.0,
        'deltaAmountInBaseCurrency': 0.0,
        'increasesExposure': false,
        'allocationEvidenceStructurallyReady': true,
        'advisoryStatus': 'no_advice',
        'recommendationCandidateReady': false,
        'productionEligible': false,
        'allocationEligible': false,
        'automaticTrading': false,
      },
    },
  };
}

void main() {
  test('maps sealed non-advisory allocation and preserves excess capital', () async {
    late Map<String, dynamic> requestBody;
    final client = MockClient((request) async {
      requestBody = jsonDecode(request.body) as Map<String, dynamic>;
      return http.Response(jsonEncode(_safeResponse()), 200);
    });
    final source = AthenaBackendPortfolioAllocationDataSource(
      baseUrl: 'http://localhost:8000',
      client: client,
    );

    final result = await source.buildAuthorizedCandidate(
      uncertaintyBoundActionCandidateFingerprint: _fpA,
      allocationPolicyId: 'policy-v1',
      economicContract: const {'economicContractFingerprint': _fpB},
      referenceCapital: 10000,
      baseCurrency: 'eur',
      positions: const [],
      correlationEvidenceFingerprints: const [_fpE],
      asOf: DateTime.utc(2026, 9, 5, 12),
    );

    expect(requestBody.containsKey('correlationEvidence'), isFalse);
    expect(requestBody.containsKey('currentPortfolioValueInBaseCurrency'), isFalse);
    expect(requestBody['correlationEvidenceFingerprints'], [_fpE]);
    expect(result.action, 'hold');
    expect(result.referenceCapital, 10000);
    expect(result.investedPositionsValueInBaseCurrency, 12500);
    expect(result.excessOverReferenceCapital, 2500);
    expect(result.shortfallVsReferenceCapital, 0);
    expect(result.correlationEvidenceFingerprints, [_fpE]);
  });

  test('fails closed if backend attempts to enable allocation', () async {
    final payload = _safeResponse();
    (payload['data'] as Map<String, dynamic>)['allocationEligible'] = true;
    final client = MockClient((_) async => http.Response(jsonEncode(payload), 200));
    final source = AthenaBackendPortfolioAllocationDataSource(
      baseUrl: 'http://localhost:8000',
      client: client,
    );

    expect(
      () => source.buildAuthorizedCandidate(
        uncertaintyBoundActionCandidateFingerprint: _fpA,
        allocationPolicyId: 'policy-v1',
        economicContract: const {'economicContractFingerprint': _fpB},
        referenceCapital: 10000,
        baseCurrency: 'EUR',
        positions: const [],
        correlationEvidenceFingerprints: const [_fpE],
        asOf: DateTime.utc(2026, 9, 5, 12),
      ),
      throwsA(isA<FormatException>()),
    );
  });

  test('fails closed when backend changes PIT cutoff', () async {
    final payload = _safeResponse();
    (payload['data'] as Map<String, dynamic>)['asOf'] = '2026-09-05T12:00:01Z';
    final client = MockClient((_) async => http.Response(jsonEncode(payload), 200));
    final source = AthenaBackendPortfolioAllocationDataSource(
      baseUrl: 'http://localhost:8000',
      client: client,
    );

    expect(
      () => source.buildAuthorizedCandidate(
        uncertaintyBoundActionCandidateFingerprint: _fpA,
        allocationPolicyId: 'policy-v1',
        economicContract: const {'economicContractFingerprint': _fpB},
        referenceCapital: 10000,
        baseCurrency: 'EUR',
        positions: const [],
        correlationEvidenceFingerprints: const [_fpE],
        asOf: DateTime.utc(2026, 9, 5, 12),
      ),
      throwsA(isA<FormatException>()),
    );
  });

  test('rejects duplicate correlation authority fingerprints before HTTP', () async {
    var called = false;
    final client = MockClient((_) async {
      called = true;
      return http.Response('{}', 500);
    });
    final source = AthenaBackendPortfolioAllocationDataSource(
      baseUrl: 'http://localhost:8000',
      client: client,
    );

    expect(
      () => source.buildAuthorizedCandidate(
        uncertaintyBoundActionCandidateFingerprint: _fpA,
        allocationPolicyId: 'policy-v1',
        economicContract: const {'economicContractFingerprint': _fpB},
        referenceCapital: 10000,
        baseCurrency: 'EUR',
        positions: const [],
        correlationEvidenceFingerprints: const [_fpE, _fpE],
        asOf: DateTime.utc(2026, 9, 5, 12),
      ),
      throwsA(isA<StateError>()),
    );
    expect(called, isFalse);
  });
}
