import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/recommendations/data/datasources/athena_backend_professional_dossier_data_source.dart';

Map<String, dynamic> _modules() => {
      for (final name in ProfessionalDossier.moduleNames)
        name: {
          'status': 'not_yet_evidenced',
          'productionEligible': false,
          'reason': 'No existe todavía evidencia PIT sellada.',
        },
    };

Map<String, dynamic> _dossier() => {
      'status': 'professional_dossier_no_production_recommendation',
      'asOf': '2026-09-07T08:00:00Z',
      'symbol': 'AAPL',
      'instrumentId': 7,
      'decision': null,
      'evidence': {
        'productionRecommendationAuthorized': false,
        'productionAllocationAuthorized': false,
      },
      'professionalModules': _modules(),
      'advisoryStatus': 'no_advice',
      'productionEligible': false,
      'allocationEligible': false,
      'executionEligible': false,
      'orderRoutingEligible': false,
      'automaticTrading': false,
      'readOnly': true,
    };

void main() {
  group('AthenaBackendProfessionalDossierDataSource', () {
    test('mapea los once módulos como no productivos y mantiene no_advice',
        () async {
      final client = MockClient((request) async {
        expect(
          request.url.path,
          '/api/v1/recommendations/production/professional-dossier',
        );
        expect(request.url.queryParameters['symbol'], 'AAPL');
        expect(request.url.queryParameters['instrumentId'], '7');
        expect(request.url.queryParameters['as_of'], isNotNull);
        return http.Response(jsonEncode({'data': _dossier()}), 200);
      });
      final source = AthenaBackendProfessionalDossierDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final result = await source.getLatest(
        asOf: DateTime.utc(2026, 9, 7, 8),
        symbol: 'aapl',
        instrumentId: 7,
      );

      expect(result.isSafe, isTrue);
      expect(result.advisoryStatus, 'no_advice');
      expect(result.productionEligible, isFalse);
      expect(result.allocationEligible, isFalse);
      expect(result.modules.keys.toSet(), ProfessionalDossier.moduleNames);
      expect(result.modules, contains('dividendTotalReturn'));
      expect(result.modules['dividendTotalReturn']!.productionEligible, isFalse);
      expect(result.modules['dividendTotalReturn']!.recommendationInfluence, isFalse);
      expect(result.modules['dividendTotalReturn']!.automaticTrading, isFalse);
      expect(ProfessionalDossier.moduleNames.length, 11);
      expect(
        result.modules.values.every((module) => !module.productionEligible),
        isTrue,
      );
    });

    test('rechaza cualquier módulo marcado productivo sin evidencia sellada',
        () async {
      final data = _dossier();
      (data['professionalModules'] as Map<String, dynamic>)['athenaRadar'] = {
        'status': 'ready',
        'productionEligible': true,
        'reason': 'inválido',
      };
      final source = AthenaBackendProfessionalDossierDataSource(
        baseUrl: 'https://api.athena.test',
        client: MockClient(
          (_) async => http.Response(jsonEncode({'data': data}), 200),
        ),
      );

      expect(source.getLatest(), throwsFormatException);
    });

    test('rechaza ejecución, order routing y trading automático', () async {
      for (final field in [
        'executionEligible',
        'orderRoutingEligible',
        'automaticTrading',
      ]) {
        final data = _dossier();
        data[field] = true;
        final source = AthenaBackendProfessionalDossierDataSource(
          baseUrl: 'https://api.athena.test',
          client: MockClient(
            (_) async => http.Response(jsonEncode({'data': data}), 200),
          ),
        );

        expect(source.getLatest(), throwsFormatException, reason: field);
      }
    });

    test('rechaza un advisoryStatus distinto de no_advice aunque los flags sean falsos', () async {
      final data = _dossier()..['advisoryStatus'] = 'advice';
      final source = AthenaBackendProfessionalDossierDataSource(
        baseUrl: 'https://api.athena.test',
        client: MockClient(
          (_) async => http.Response(jsonEncode({'data': data}), 200),
        ),
      );
      addTearDown(source.dispose);
      expect(source.getLatest(symbol: 'AAPL'), throwsFormatException);
    });

    test('rechaza no_advice si se intenta elevar elegibilidad', () async {
      for (final field in ['productionEligible', 'allocationEligible']) {
        final data = _dossier();
        data[field] = true;
        final source = AthenaBackendProfessionalDossierDataSource(
          baseUrl: 'https://api.athena.test',
          client: MockClient(
            (_) async => http.Response(jsonEncode({'data': data}), 200),
          ),
        );

        expect(source.getLatest(), throwsFormatException, reason: field);
      }
    });

    test('rechaza módulos faltantes o desconocidos', () async {
      final missing = _dossier();
      (missing['professionalModules'] as Map<String, dynamic>)
          .remove('expectationsGap');
      final missingSource = AthenaBackendProfessionalDossierDataSource(
        baseUrl: 'https://api.athena.test',
        client: MockClient(
          (_) async => http.Response(jsonEncode({'data': missing}), 200),
        ),
      );
      expect(missingSource.getLatest(), throwsFormatException);

      final unknown = _dossier();
      (unknown['professionalModules'] as Map<String, dynamic>)['unknown'] = {
        'status': 'not_yet_evidenced',
        'productionEligible': false,
        'reason': 'inválido',
      };
      final unknownSource = AthenaBackendProfessionalDossierDataSource(
        baseUrl: 'https://api.athena.test',
        client: MockClient(
          (_) async => http.Response(jsonEncode({'data': unknown}), 200),
        ),
      );
      expect(unknownSource.getLatest(), throwsFormatException);
    });
  });
    test('rechaza un dossier de otro símbolo incluso si sus módulos son seguros',
        () async {
      final data = _dossier()..['symbol'] = 'MSFT';
      final source = AthenaBackendProfessionalDossierDataSource(
        baseUrl: 'https://api.athena.test',
        client: MockClient(
          (_) async => http.Response(jsonEncode({'data': data}), 200),
        ),
      );
      addTearDown(source.dispose);

      expect(source.getLatest(symbol: 'AAPL'), throwsFormatException);
    });

    test('rechaza un instrumento distinto y una identidad ausente',
        () async {
      for (final identity in [8, null]) {
        final data = _dossier()..['instrumentId'] = identity;
        final source = AthenaBackendProfessionalDossierDataSource(
          baseUrl: 'https://api.athena.test',
          client: MockClient(
            (_) async => http.Response(jsonEncode({'data': data}), 200),
          ),
        );
        addTearDown(source.dispose);
        expect(
          source.getLatest(symbol: 'AAPL', instrumentId: 7),
          throwsFormatException,
        );
      }
    });

    test('presenta medidas PIT de dividendos sin elevar autoridad', () async {
      final data = _dossier();
      (data['professionalModules'] as Map<String, dynamic>)['dividendTotalReturn'] = {
        'status': 'diagnostic_evidence_available',
        'productionEligible': false,
        'recommendationInfluence': false,
        'automaticTrading': false,
        'reason': 'Diagnóstico descriptivo',
        'evidence': {
          'knowledgeCutoff': '2026-09-07T08:00:00Z',
          'productionEligible': false,
          'automaticTrading': false,
          'signal': {
            'status': 'diagnostic_ready',
            'symbol': 'AAPL',
            'asOf': '2026-09-07T08:00:00Z',
            'productionEligible': false,
            'dividend': {
              'pitSafe': true,
              'knowledgeCutoff': '2026-09-07T08:00:00Z',
              'frequency': 'quarterly',
              'trailingYield': 0.02,
              'dividendGrowthRate': -0.1,
              'paymentStabilityScore': 0.9,
            },
            'totalReturn60d': -0.05,
            'earningsPayoutRatio': null,
            'fcfPayoutRatio': 0.4,
            'financialPeriodSustainability': null,
          },
        },
      };
      final source = AthenaBackendProfessionalDossierDataSource(
        baseUrl: 'https://api.athena.test',
        client: MockClient((_) async => http.Response(jsonEncode({'data': data}), 200)),
      );
      addTearDown(source.dispose);
      final result = await source.getLatest(symbol: 'AAPL');
      final metrics = result.modules['dividendTotalReturn']!.dividendDiagnostics!;
      expect(result.isSafe, isTrue);
      expect(metrics.frequency, 'quarterly');
      expect(metrics.trailingYield, 0.02);
      expect(metrics.dividendGrowthRate, -0.1);
      expect(metrics.totalReturn60d, -0.05);
      expect(metrics.earningsPayoutRatio, isNull);
    });

    test('rechaza identidad, PIT y medidas no finitas en evidencia económica', () async {
      for (final mutation in <void Function(Map<String, dynamic>)>[
        (signal) => signal['symbol'] = 'MSFT',
        (signal) => signal['asOf'] = '2026-09-08T08:00:00Z',
        (signal) => (signal['dividend'] as Map<String, dynamic>)['knowledgeCutoff'] = '2026-09-08T08:00:00Z',
        (signal) => signal['totalReturn60d'] = 'Infinity',
        (signal) => signal['productionEligible'] = true,
      ]) {
        final data = _dossier();
        (data['professionalModules'] as Map<String, dynamic>)['dividendTotalReturn'] = {
          'status': 'diagnostic_evidence_available',
          'productionEligible': false,
          'recommendationInfluence': false,
          'automaticTrading': false,
          'reason': 'Diagnóstico',
          'evidence': {
            'knowledgeCutoff': '2026-09-07T08:00:00Z',
            'productionEligible': false,
            'automaticTrading': false,
            'signal': {
              'status': 'diagnostic_ready',
              'symbol': 'AAPL',
              'asOf': '2026-09-07T08:00:00Z',
              'productionEligible': false,
              'dividend': {
                'pitSafe': true,
                'knowledgeCutoff': '2026-09-07T08:00:00Z',
                'frequency': 'quarterly',
                'trailingYield': 0.02,
              },
              'totalReturn60d': 0.01,
            },
          },
        };
        final signal = ((data['professionalModules'] as Map<String, dynamic>)['dividendTotalReturn']
            as Map<String, dynamic>)['evidence'] as Map<String, dynamic>;
        mutation(signal['signal'] as Map<String, dynamic>);
        final source = AthenaBackendProfessionalDossierDataSource(
          baseUrl: 'https://api.athena.test',
          client: MockClient((_) async => http.Response(jsonEncode({'data': data}), 200)),
        );
        addTearDown(source.dispose);
        expect(source.getLatest(symbol: 'AAPL'), throwsFormatException);
      }
    });

}
