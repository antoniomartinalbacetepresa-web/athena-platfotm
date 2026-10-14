import 'dart:convert';

import 'package:app/features/portfolio/data/athena_backend_portfolio_allocation_policy_data_source.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  Map<String, dynamic> policy({
    String policyId = 'balanced-usd-v1',
    String fingerprint = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  }) => {
        'artifactVersion': 'athena-allocation-policy-v1',
        'policyId': policyId,
        'baseCurrency': 'USD',
        'maximumInstrumentSleeveWeight': 0.20,
        'minimumCashReserveWeight': 0.10,
        'maximumAbsolutePairCorrelation': 0.80,
        'minimumCorrelationSampleCount': 60,
        'maximumCorrelationAgeSeconds': 86400,
        'semantics': {
          'referenceCapitalIsUserOwnedAllocationBase': true,
          'singleAssetExposureIsNotPortfolioWeight': true,
          'fullLongMeansFillInstrumentSleeveNotWholePortfolio': true,
          'reducedLongScalesInstrumentSleeveByFrozenEconomicContract': true,
          'sellTargetsZeroInstrumentWeight': true,
          'holdPreservesCurrentVerifiedWeight': true,
        },
        'policy': {
          'codeDefaultTargetWeight': false,
          'codeDefaultCorrelationThreshold': false,
          'codeDefaultStalenessThreshold': false,
          'automaticTrading': false,
        },
        'registeredAt': '2026-09-06T12:00:00.000Z',
        'policyFingerprint': fingerprint,
      };

  Map<String, dynamic> envelope(Map<String, dynamic> value) => {
        'policy': value,
        'persistence': {
          'persisted': true,
          'registeredAt': value['registeredAt'],
          'policyFingerprint': value['policyFingerprint'],
        },
        'advisoryStatus': 'no_advice',
        'recommendationCandidateReady': false,
        'productionEligible': false,
        'allocationEligible': false,
        'automaticTrading': false,
        'policySelectionPerformed': false,
        'defaultPolicyExists': false,
      };

  Map<String, dynamic> response(List<Map<String, dynamic>> data) => {
        'data': data,
        'selection': {
          'explicitSelectionRequired': true,
          'policySelectionPerformed': false,
          'defaultPolicyExists': false,
          'automaticTrading': false,
        },
      };

  test('loads persisted policies without server-side selection', () async {
    final dataSource = AthenaBackendPortfolioAllocationPolicyDataSource(
      baseUrl: 'http://localhost:8000',
      client: MockClient((request) async {
        expect(request.method, 'GET');
        expect(request.url.path, '/api/v1/portfolio/allocation-policies');
        return http.Response(
          jsonEncode(response([envelope(policy())])),
          200,
          headers: const {'content-type': 'application/json'},
        );
      }),
    );

    final policies = await dataSource.listPolicies();

    expect(policies, hasLength(1));
    expect(policies.single.policyId, 'balanced-usd-v1');
    expect(policies.single.baseCurrency, 'USD');
    expect(policies.single.maximumInstrumentSleeveWeight, 0.20);
    dataSource.dispose();
  });

  test('rejects backend default or implicit policy selection', () async {
    final body = response([envelope(policy())]);
    final selection = body['selection']! as Map<String, dynamic>;
    selection['defaultPolicyExists'] = true;
    final dataSource = AthenaBackendPortfolioAllocationPolicyDataSource(
      baseUrl: 'http://localhost:8000',
      client: MockClient((request) async => http.Response(jsonEncode(body), 200)),
    );

    expect(dataSource.listPolicies(), throwsA(isA<FormatException>()));
    dataSource.dispose();
  });

  test('rejects mismatched persistence fingerprint', () async {
    final item = envelope(policy());
    final persistence = item['persistence']! as Map<String, dynamic>;
    persistence['policyFingerprint'] =
        'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
    final dataSource = AthenaBackendPortfolioAllocationPolicyDataSource(
      baseUrl: 'http://localhost:8000',
      client: MockClient((request) async =>
          http.Response(jsonEncode(response([item])), 200)),
    );

    expect(dataSource.listPolicies(), throwsA(isA<FormatException>()));
    dataSource.dispose();
  });

  test('rejects duplicate persisted policy IDs', () async {
    final first = envelope(policy());
    final second = envelope(policy(
      fingerprint:
          'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
    ));
    final dataSource = AthenaBackendPortfolioAllocationPolicyDataSource(
      baseUrl: 'http://localhost:8000',
      client: MockClient((request) async =>
          http.Response(jsonEncode(response([first, second])), 200)),
    );

    expect(dataSource.listPolicies(), throwsA(isA<FormatException>()));
    dataSource.dispose();
  });
}
