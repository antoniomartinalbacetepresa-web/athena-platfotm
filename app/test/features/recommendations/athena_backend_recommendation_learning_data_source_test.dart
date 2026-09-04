import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/recommendations/data/datasources/athena_backend_recommendation_learning_data_source.dart';

Map<String, dynamic> _safeData({int horizonDays = 90}) {
  return {
    'status': 'learning_diagnostics_only',
    'asOf': '2026-09-01T20:30:00Z',
    'filters': {
      'modelVersion': 'athena-v1',
      'horizonDays': horizonDays,
    },
    'performance': {'sampleSize': 42},
    'calibration': {'status': 'review_required'},
    'evaluationSchedule': {'dueCount': 3},
    'drift': {'status': 'stable'},
    'shadowLiveLongitudinal': {
      'status': 'shadow_live_longitudinal_evidence_available',
      'persistedCandidateCount': 8,
      'eligibleCandidateCount': 7,
      'evaluatedCandidateCount': 5,
      'evaluatedObservationCount': 12,
      'skippedFutureCandidateCount': 1,
      'advisoryStatus': 'no_advice',
      'productionEligible': false,
      'recommendationCandidateReady': false,
      'policy': {
        'automaticModelMutation': false,
        'automaticProductionPromotion': false,
        'automaticTrading': false,
      },
    },
    'advisoryStatus': 'no_advice',
    'productionEligible': false,
    'automaticModelMutation': false,
    'automaticProductionPromotion': false,
    'automaticTrading': false,
  };
}

void main() {
  group('AthenaBackendRecommendationLearningDataSource', () {
    test('obtiene y normaliza el estado shadow real de aprendizaje', () async {
      final client = MockClient((request) async {
        expect(request.url.path, '/api/v1/recommendations/learning/status');
        expect(request.url.queryParameters['modelVersion'], 'athena-v1');
        expect(request.url.queryParameters['horizonDays'], '90');
        expect(request.url.queryParameters['as_of'], isNotNull);
        return http.Response(jsonEncode({'data': _safeData()}), 200);
      });

      final dataSource = AthenaBackendRecommendationLearningDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );
      final status = await dataSource.getStatus(
        asOf: DateTime.utc(2026, 9, 1, 20, 30),
        modelVersion: 'athena-v1',
        horizonDays: 90,
      );

      expect(status.status, 'learning_diagnostics_only');
      expect(status.isDiagnosticOnly, isTrue);
      expect(status.modelVersion, 'athena-v1');
      expect(status.horizonDays, 90);
      expect(status.performance['sampleSize'], 42);
      expect(status.calibration['status'], 'review_required');
      expect(status.evaluationSchedule['dueCount'], 3);
      expect(status.drift?['status'], 'stable');
      expect(status.persistedShadowCandidateCount, 8);
      expect(status.eligibleShadowCandidateCount, 7);
      expect(status.evaluatedShadowCandidateCount, 5);
      expect(status.evaluatedShadowObservationCount, 12);
      expect(status.hasMatureShadowEvidence, isTrue);
      expect(status.isShadowSafe, isTrue);
      expect(status.requiresHumanReview, isTrue);
    });

    test('permite estado sin filtro ni drift', () async {
      final client = MockClient((request) async {
        expect(request.url.queryParameters, isEmpty);
        final data = _safeData();
        data['filters'] = {'modelVersion': null, 'horizonDays': null};
        data['drift'] = null;
        return http.Response(jsonEncode({'data': data}), 200);
      });
      final dataSource = AthenaBackendRecommendationLearningDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final status = await dataSource.getStatus();

      expect(status.modelVersion, isNull);
      expect(status.horizonDays, isNull);
      expect(status.drift, isNull);
    });

    test('rechaza horizonte no positivo antes de llamar al backend', () async {
      var calls = 0;
      final client = MockClient((_) async {
        calls += 1;
        return http.Response('{}', 200);
      });
      final dataSource = AthenaBackendRecommendationLearningDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      expect(() => dataSource.getStatus(horizonDays: 0), throwsArgumentError);
      expect(calls, 0);
    });

    test('rechaza respuesta sin asOf UTC válido', () async {
      final client = MockClient((_) async {
        final data = _safeData();
        data['asOf'] = '2026-09-01T20:30:00';
        return http.Response(jsonEncode({'data': data}), 200);
      });
      final dataSource = AthenaBackendRecommendationLearningDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      expect(dataSource.getStatus, throwsFormatException);
    });

    test('rechaza escalado productivo o trading desde backend', () async {
      for (final field in [
        'productionEligible',
        'automaticModelMutation',
        'automaticProductionPromotion',
        'automaticTrading',
      ]) {
        final client = MockClient((_) async {
          final data = _safeData();
          data[field] = true;
          return http.Response(jsonEncode({'data': data}), 200);
        });
        final dataSource = AthenaBackendRecommendationLearningDataSource(
          baseUrl: 'https://api.athena.test',
          client: client,
        );
        expect(dataSource.getStatus, throwsFormatException, reason: field);
      }
    });

    test('rechaza contrato shadow inseguro y contadores inválidos', () async {
      final unsafeClient = MockClient((_) async {
        final data = _safeData();
        final shadow = Map<String, dynamic>.from(
          data['shadowLiveLongitudinal'] as Map,
        );
        shadow['recommendationCandidateReady'] = true;
        data['shadowLiveLongitudinal'] = shadow;
        return http.Response(jsonEncode({'data': data}), 200);
      });
      final unsafeSource = AthenaBackendRecommendationLearningDataSource(
        baseUrl: 'https://api.athena.test',
        client: unsafeClient,
      );
      expect(unsafeSource.getStatus, throwsFormatException);

      final invalidCountClient = MockClient((_) async {
        final data = _safeData();
        final shadow = Map<String, dynamic>.from(
          data['shadowLiveLongitudinal'] as Map,
        );
        shadow['evaluatedObservationCount'] = -1;
        data['shadowLiveLongitudinal'] = shadow;
        return http.Response(jsonEncode({'data': data}), 200);
      });
      final invalidCountSource = AthenaBackendRecommendationLearningDataSource(
        baseUrl: 'https://api.athena.test',
        client: invalidCountClient,
      );
      expect(invalidCountSource.getStatus, throwsFormatException);
    });
  });
}
