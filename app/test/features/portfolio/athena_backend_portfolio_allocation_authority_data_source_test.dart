import 'dart:convert';

import 'package:app/features/portfolio/data/athena_backend_portfolio_allocation_authority_data_source.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  final asOf = DateTime.parse('2026-09-05T12:00:00Z');

  test('resolves exact server-owned allocation authorities', () async {
    late Map<String, dynamic> requestBody;
    final dataSource = AthenaBackendPortfolioAllocationAuthorityDataSource(
      baseUrl: 'http://localhost:8000',
      client: MockClient((request) async {
        requestBody = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(
          jsonEncode({
            'data': {
              'artifactVersion': 'athena-allocation-authority-resolution-v1',
              'status': 'allocation_authorities_resolved_non_advisory',
              'asOf': '2026-09-05T12:00:00.000Z',
              'instrumentId': 7,
              'horizonDays': 30,
              'uncertaintyBoundActionCandidateFingerprint': 'a' * 64,
              'actionAuthorityRecordFingerprint': 'b' * 64,
              'correlationEvidenceFingerprints': ['c' * 64],
              'allocationAuthoritiesReady': true,
              'callerSuppliedInternalFingerprintsRequired': false,
              'policySelectionPerformed': false,
              'economicContractInvented': false,
              'advisoryStatus': 'no_advice',
              'recommendationCandidateReady': false,
              'productionEligible': false,
              'allocationEligible': false,
              'automaticTrading': false,
            },
          }),
          200,
          headers: const {'content-type': 'application/json'},
        );
      }),
    );

    final result = await dataSource.resolve(
      instrumentId: 7,
      horizonDays: 30,
      heldInstrumentIds: const [7, 9],
      asOf: asOf,
    );

    expect(result.ready, isTrue);
    expect(result.actionCandidateFingerprint, 'a' * 64);
    expect(result.correlationEvidenceFingerprints, ['c' * 64]);
    expect(requestBody.containsKey('uncertaintyBoundActionCandidateFingerprint'), isFalse);
    expect(requestBody.containsKey('correlationEvidenceFingerprints'), isFalse);
    expect(requestBody['instrumentId'], 7);
    expect(requestBody['heldInstrumentIds'], [7, 9]);
    dataSource.dispose();
  });

  test('keeps missing authority as explicit non-advisory not-ready state', () async {
    final dataSource = AthenaBackendPortfolioAllocationAuthorityDataSource(
      baseUrl: 'http://localhost:8000',
      client: MockClient((request) async => http.Response(
            jsonEncode({
              'data': {
                'artifactVersion': 'athena-allocation-authority-resolution-v1',
                'status': 'allocation_authorities_not_ready',
                'asOf': '2026-09-05T12:00:00.000Z',
                'instrumentId': 7,
                'horizonDays': 30,
                'allocationAuthoritiesReady': false,
                'reason': 'action_authority_missing',
                'callerSuppliedInternalFingerprintsRequired': false,
                'policySelectionPerformed': false,
                'economicContractInvented': false,
                'advisoryStatus': 'no_advice',
                'recommendationCandidateReady': false,
                'productionEligible': false,
                'allocationEligible': false,
                'automaticTrading': false,
              },
            }),
            200,
          )),
    );

    final result = await dataSource.resolve(
      instrumentId: 7,
      horizonDays: 30,
      heldInstrumentIds: const [],
      asOf: asOf,
    );

    expect(result.ready, isFalse);
    expect(result.reason, 'action_authority_missing');
    expect(result.actionCandidateFingerprint, isNull);
    expect(result.correlationEvidenceFingerprints, isEmpty);
    dataSource.dispose();
  });

  test('rejects backend production escape', () async {
    final dataSource = AthenaBackendPortfolioAllocationAuthorityDataSource(
      baseUrl: 'http://localhost:8000',
      client: MockClient((request) async => http.Response(
            jsonEncode({
              'data': {
                'artifactVersion': 'athena-allocation-authority-resolution-v1',
                'status': 'allocation_authorities_not_ready',
                'asOf': '2026-09-05T12:00:00.000Z',
                'instrumentId': 7,
                'horizonDays': 30,
                'allocationAuthoritiesReady': false,
                'reason': 'action_authority_missing',
                'callerSuppliedInternalFingerprintsRequired': false,
                'policySelectionPerformed': false,
                'economicContractInvented': false,
                'advisoryStatus': 'no_advice',
                'recommendationCandidateReady': false,
                'productionEligible': true,
                'allocationEligible': false,
                'automaticTrading': false,
              },
            }),
            200,
          )),
    );

    expect(
      () => dataSource.resolve(
        instrumentId: 7,
        horizonDays: 30,
        heldInstrumentIds: const [],
        asOf: asOf,
      ),
      throwsA(isA<FormatException>()),
    );
    dataSource.dispose();
  });

  test('rejects duplicate held instrument IDs before HTTP', () async {
    var called = false;
    final dataSource = AthenaBackendPortfolioAllocationAuthorityDataSource(
      baseUrl: 'http://localhost:8000',
      client: MockClient((request) async {
        called = true;
        return http.Response('{}', 200);
      }),
    );

    expect(
      () => dataSource.resolve(
        instrumentId: 7,
        horizonDays: 30,
        heldInstrumentIds: const [9, 9],
        asOf: asOf,
      ),
      throwsA(isA<StateError>()),
    );
    expect(called, isFalse);
    dataSource.dispose();
  });
}
