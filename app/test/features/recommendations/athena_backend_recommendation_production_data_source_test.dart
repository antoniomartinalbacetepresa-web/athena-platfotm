import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/recommendations/data/datasources/athena_backend_recommendation_production_data_source.dart';

const _recommendationFingerprint =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const _allocationFingerprint =
    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
const _economicFingerprint =
    'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc';
const _authorizationReason =
    'Evidencia OOS validada y revisión humana confirmada para este artefacto.';

Map<String, dynamic> _recommendation() => {
      'status': 'production_recommendation_authorized',
      'advisoryStatus': 'production_recommendation',
      'recommendationCandidateReady': true,
      'productionEligible': true,
      'allocationEligible': false,
      'automaticTrading': false,
      'authorizationFingerprint': _recommendationFingerprint,
      'instrumentId': '7',
      'symbol': 'AAPL',
      'action': 'buy',
      'policyState': 'flat',
      'economicContractFingerprint': _economicFingerprint,
      'asOf': '2026-09-01T11:00:00Z',
      'authorizedAt': '2026-09-01T11:30:00Z',
      'authorizationReason': _authorizationReason,
      'horizonDays': 30,
      'expectedExcessReturn': 0.0425,
    };

Map<String, dynamic> _allocation() => {
      'status': 'production_allocation_authorized',
      'advisoryStatus': 'production_allocation',
      'productionEligible': true,
      'allocationEligible': true,
      'executionEligible': false,
      'orderRoutingEligible': false,
      'automaticTrading': false,
      'authorizationFingerprint': _allocationFingerprint,
      'recommendationAuthorizationFingerprint': _recommendationFingerprint,
      'economicContractFingerprint': _economicFingerprint,
      'instrumentId': 7,
      'symbol': 'AAPL',
      'action': 'buy',
      'baseCurrency': 'EUR',
      'referenceCapital': 10000.0,
      'targetAmountInBaseCurrency': 1500.0,
      'deltaAmountInBaseCurrency': 1500.0,
      'asOf': '2026-09-01T11:00:00Z',
      'authorizedAt': '2026-09-01T11:45:00Z',
    };

Map<String, dynamic> _state({bool withAllocation = true}) => {
      'asOf': '2026-09-01T12:00:00Z',
      'symbol': null,
      'instrumentId': null,
      'recommendation': _recommendation(),
      'allocation': withAllocation ? _allocation() : null,
      'productionRecommendationAvailable': true,
      'productionAllocationAvailable': withAllocation,
      'automaticTrading': false,
      'readOnly': true,
    };

void main() {
  group('AthenaBackendRecommendationProductionDataSource', () {
    test('mapea recomendación, motivo sellado, señal OOS y allocation ligados sin habilitar ejecución', () async {
      final client = MockClient((request) async {
        expect(request.url.path, '/api/v1/recommendations/production/latest');
        expect(request.url.queryParameters['as_of'], isNotNull);
        return http.Response(jsonEncode({'data': _state()}), 200);
      });
      final source = AthenaBackendRecommendationProductionDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final result = await source.getLatest(asOf: DateTime.utc(2026, 9, 1, 12));

      expect(result.isSafe, isTrue);
      expect(result.recommendation?.instrumentId, 7);
      expect(result.recommendation?.symbol, 'AAPL');
      expect(result.recommendation?.action, 'buy');
      expect(result.recommendation?.authorizationReason, _authorizationReason);
      expect(result.recommendation?.horizonDays, 30);
      expect(result.recommendation?.expectedExcessReturn, 0.0425);
      expect(result.allocation?.baseCurrency, 'EUR');
      expect(result.allocation?.targetAmountInBaseCurrency, 1500.0);
      expect(result.automaticTrading, isFalse);
      expect(result.readOnly, isTrue);
    });

    test('mantiene compatibilidad con autorización sin señal explicativa cuantitativa', () async {
      final data = _state(withAllocation: false);
      final recommendation = data['recommendation'] as Map<String, dynamic>;
      recommendation.remove('horizonDays');
      recommendation.remove('expectedExcessReturn');
      final client = MockClient((_) async =>
          http.Response(jsonEncode({'data': data}), 200));
      final source = AthenaBackendRecommendationProductionDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final result = await source.getLatest();

      expect(result.isSafe, isTrue);
      expect(result.recommendation?.authorizationReason, _authorizationReason);
      expect(result.recommendation?.horizonDays, isNull);
      expect(result.recommendation?.expectedExcessReturn, isNull);
    });

    test('rechaza autorización productiva sin motivo sellado', () async {
      for (final value in [null, '', '   ']) {
        final data = _state();
        (data['recommendation'] as Map<String, dynamic>)['authorizationReason'] = value;
        final client = MockClient((_) async =>
            http.Response(jsonEncode({'data': data}), 200));
        final source = AthenaBackendRecommendationProductionDataSource(
          baseUrl: 'https://api.athena.test',
          client: client,
        );

        expect(source.getLatest(), throwsFormatException, reason: '$value');
      }
    });

    test('rechaza señal productiva no finita', () async {
      for (final value in ['NaN', 'Infinity', '-Infinity']) {
        final data = _state();
        (data['recommendation'] as Map<String, dynamic>)['expectedExcessReturn'] = value;
        final client = MockClient((_) async =>
            http.Response(jsonEncode({'data': data}), 200));
        final source = AthenaBackendRecommendationProductionDataSource(
          baseUrl: 'https://api.athena.test',
          client: client,
        );

        expect(source.getLatest(), throwsFormatException, reason: value);
      }
    });

    test('rechaza horizonte productivo no positivo', () async {
      for (final value in [0, -1, '0']) {
        final data = _state();
        (data['recommendation'] as Map<String, dynamic>)['horizonDays'] = value;
        final client = MockClient((_) async =>
            http.Response(jsonEncode({'data': data}), 200));
        final source = AthenaBackendRecommendationProductionDataSource(
          baseUrl: 'https://api.athena.test',
          client: client,
        );

        expect(source.getLatest(), throwsFormatException, reason: '$value');
      }
    });

    test('acepta ausencia productiva explícita sin inventar recomendación', () async {
      final client = MockClient((_) async => http.Response(
            jsonEncode({
              'data': {
                'asOf': '2026-09-01T12:00:00Z',
                'symbol': null,
                'instrumentId': null,
                'recommendation': null,
                'allocation': null,
                'productionRecommendationAvailable': false,
                'productionAllocationAvailable': false,
                'automaticTrading': false,
                'readOnly': true,
              },
            }),
            200,
          ));
      final source = AthenaBackendRecommendationProductionDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final result = await source.getLatest();

      expect(result.isSafe, isTrue);
      expect(result.productionRecommendationAvailable, isFalse);
      expect(result.recommendation, isNull);
      expect(result.allocation, isNull);
    });

    test('rechaza recomendación productiva con trading automático', () async {
      final data = _state();
      (data['recommendation'] as Map<String, dynamic>)['automaticTrading'] = true;
      final client = MockClient((_) async =>
          http.Response(jsonEncode({'data': data}), 200));
      final source = AthenaBackendRecommendationProductionDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      expect(source.getLatest(), throwsFormatException);
    });

    test('rechaza allocation que habilite ejecución u order routing', () async {
      for (final field in ['executionEligible', 'orderRoutingEligible', 'automaticTrading']) {
        final data = _state();
        (data['allocation'] as Map<String, dynamic>)[field] = true;
        final client = MockClient((_) async =>
            http.Response(jsonEncode({'data': data}), 200));
        final source = AthenaBackendRecommendationProductionDataSource(
          baseUrl: 'https://api.athena.test',
          client: client,
        );

        expect(source.getLatest(), throwsFormatException, reason: field);
      }
    });

    test('rechaza allocation recompuesto con otro instrumento', () async {
      final data = _state();
      (data['allocation'] as Map<String, dynamic>)['instrumentId'] = 8;
      final client = MockClient((_) async =>
          http.Response(jsonEncode({'data': data}), 200));
      final source = AthenaBackendRecommendationProductionDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      expect(source.getLatest(), throwsFormatException);
    });

    test('rechaza capital no finito aunque llegue como texto', () async {
      final data = _state();
      (data['allocation'] as Map<String, dynamic>)['referenceCapital'] = 'NaN';
      final client = MockClient((_) async =>
          http.Response(jsonEncode({'data': data}), 200));
      final source = AthenaBackendRecommendationProductionDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      expect(source.getLatest(), throwsFormatException);
    });

    test('rechaza autorización posterior al cutoff PIT', () async {
      final data = _state();
      (data['recommendation'] as Map<String, dynamic>)['authorizedAt'] =
          '2026-09-01T13:00:00Z';
      final client = MockClient((_) async =>
          http.Response(jsonEncode({'data': data}), 200));
      final source = AthenaBackendRecommendationProductionDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      expect(source.getLatest(), throwsFormatException);
    });
  });
}
