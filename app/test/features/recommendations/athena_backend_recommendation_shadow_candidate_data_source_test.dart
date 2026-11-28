import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/recommendations/data/datasources/athena_backend_recommendation_shadow_candidate_data_source.dart';

const _candidateFingerprint =
    '1111111111111111111111111111111111111111111111111111111111111111';
const _confirmationFingerprint =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const _modelFingerprint =
    '2222222222222222222222222222222222222222222222222222222222222222';

Map<String, dynamic> _candidate() => {
      'artifactVersion': 'shadow-live-candidate-v1',
      'candidateFingerprint': _candidateFingerprint,
      'confirmationEvidenceFingerprint': _confirmationFingerprint,
      'symbol': 'AAPL',
      'instrumentId': 7,
      'asOf': '2026-09-01T11:00:00Z',
      'horizons': {
        '30': {
          'horizonDays': 30,
          'expectedExcessReturn': 0.015,
          'modelFingerprint': _modelFingerprint,
          'explanation': {
            'largestAbsoluteContributors': [
              {'feature': 'technicalScore', 'contribution': 0.01},
            ],
          },
        },
      },
      'riskContext': {'riskScore': 20.0},
      'valuationContext': {'reportedAnnualPe': 21.0},
      'fundamentalContext': {'coverageRatio': 1.0},
      'advisoryStatus': 'no_advice',
      'recommendationCandidateReady': false,
      'productionEligible': false,
      'action': null,
      'score': null,
      'conviction': null,
    };

Map<String, dynamic> _available() => {
      'status': 'shadow_candidate_available_non_advisory',
      'asOf': '2026-09-01T12:00:00Z',
      'candidateAsOf': '2026-09-01T11:00:00Z',
      'persistedAt': '2026-09-01T11:05:00Z',
      'recordId': 9,
      'candidate': _candidate(),
      'advisoryStatus': 'no_advice',
      'recommendationCandidateReady': false,
      'productionEligible': false,
      'automaticTrading': false,
    };

void main() {
  group('AthenaBackendRecommendationShadowCandidateDataSource', () {
    test('mapea candidato shadow PIT verificable sin convertirlo en consejo', () async {
      final client = MockClient((request) async {
        expect(
          request.url.path,
          '/api/v1/recommendations/shadow/latest-candidate',
        );
        expect(request.url.queryParameters['as_of'], isNotNull);
        return http.Response(jsonEncode({'data': _available()}), 200);
      });
      final source = AthenaBackendRecommendationShadowCandidateDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final result = await source.getLatest(
        asOf: DateTime.utc(2026, 9, 1, 12),
      );

      expect(result.isShadowSafe, isTrue);
      expect(result.candidate?.symbol, 'AAPL');
      expect(result.candidate?.inferredHorizons.single.horizonDays, 30);
      expect(result.candidate?.inferredHorizons.single.expectedExcessReturn, 0.015);
      expect(result.productionEligible, isFalse);
      expect(result.automaticTrading, isFalse);
    });

    test('acepta ausencia explícita de candidato', () async {
      final client = MockClient((_) async => http.Response(
            jsonEncode({
              'data': {
                'status': 'no_shadow_candidate_known_at_cutoff',
                'asOf': '2026-09-01T12:00:00Z',
                'candidate': null,
                'advisoryStatus': 'no_advice',
                'recommendationCandidateReady': false,
                'productionEligible': false,
                'automaticTrading': false,
              },
            }),
            200,
          ));
      final source = AthenaBackendRecommendationShadowCandidateDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final result = await source.getLatest();

      expect(result.hasCandidate, isFalse);
      expect(result.isShadowSafe, isTrue);
    });

    test('rechaza persistencia posterior al corte PIT', () async {
      final data = _available();
      data['persistedAt'] = '2026-09-01T13:00:00Z';
      final client = MockClient((_) async =>
          http.Response(jsonEncode({'data': data}), 200));
      final source = AthenaBackendRecommendationShadowCandidateDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      expect(source.getLatest(), throwsFormatException);
    });

    test('rechaza acción o escape productivo en artefacto shadow', () async {
      final data = _available();
      (data['candidate'] as Map<String, dynamic>)['action'] = 'buy';
      final client = MockClient((_) async =>
          http.Response(jsonEncode({'data': data}), 200));
      final source = AthenaBackendRecommendationShadowCandidateDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      expect(source.getLatest(), throwsFormatException);
    });

    test('rechaza NaN textual en expectedExcessReturn', () async {
      final data = _available();
      final candidate = data['candidate'] as Map<String, dynamic>;
      final horizons = candidate['horizons'] as Map<String, dynamic>;
      (horizons['30'] as Map<String, dynamic>)['expectedExcessReturn'] = 'NaN';
      final client = MockClient((_) async =>
          http.Response(jsonEncode({'data': data}), 200));
      final source = AthenaBackendRecommendationShadowCandidateDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      expect(source.getLatest(), throwsFormatException);
    });
  });
}
