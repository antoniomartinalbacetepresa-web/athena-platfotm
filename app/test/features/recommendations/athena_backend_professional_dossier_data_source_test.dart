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
    test('mapea los diez módulos como no productivos y mantiene no_advice',
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
}
