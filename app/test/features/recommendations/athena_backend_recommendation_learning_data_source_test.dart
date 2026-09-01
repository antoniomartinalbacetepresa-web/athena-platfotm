import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/recommendations/data/datasources/athena_backend_recommendation_learning_data_source.dart';

void main() {
  group('AthenaBackendRecommendationLearningDataSource', () {
    test('obtiene y normaliza el estado de aprendizaje', () async {
      final client = MockClient((request) async {
        expect(
          request.url.path,
          '/api/v1/recommendations/learning/status',
        );
        expect(request.url.queryParameters['modelVersion'], 'athena-v1');
        expect(request.url.queryParameters['horizonDays'], '90');
        expect(request.url.queryParameters['as_of'], isNotNull);

        return http.Response(
          jsonEncode({
            'data': {
              'status': 'learning_diagnostics_only',
              'asOf': '2026-09-01T20:30:00+00:00',
              'filters': {
                'modelVersion': 'athena-v1',
                'horizonDays': 90,
              },
              'performance': {
                'sampleSize': 42,
              },
              'calibration': {
                'status': 'review_required',
              },
              'evaluationSchedule': {
                'dueCount': 3,
              },
              'drift': {
                'status': 'stable',
              },
              'automaticModelMutation': false,
            },
          }),
          200,
        );
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
      expect(status.automaticModelMutation, isFalse);
      expect(status.requiresHumanReview, isTrue);
    });

    test('permite estado sin filtro ni drift', () async {
      final client = MockClient((request) async {
        expect(request.url.queryParameters, isEmpty);
        return http.Response(
          jsonEncode({
            'data': {
              'status': 'learning_diagnostics_only',
              'asOf': '2026-09-01T20:30:00Z',
              'filters': {
                'modelVersion': null,
                'horizonDays': null,
              },
              'performance': {},
              'calibration': {},
              'evaluationSchedule': {},
              'drift': null,
              'automaticModelMutation': false,
            },
          }),
          200,
        );
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

      expect(
        () => dataSource.getStatus(horizonDays: 0),
        throwsArgumentError,
      );
      expect(calls, 0);
    });

    test('rechaza respuesta sin asOf válido', () async {
      final client = MockClient((_) async {
        return http.Response(
          jsonEncode({
            'data': {
              'status': 'learning_diagnostics_only',
              'filters': {},
              'performance': {},
              'calibration': {},
              'evaluationSchedule': {},
              'automaticModelMutation': false,
            },
          }),
          200,
        );
      });
      final dataSource = AthenaBackendRecommendationLearningDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      expect(dataSource.getStatus, throwsFormatException);
    });
  });
}
