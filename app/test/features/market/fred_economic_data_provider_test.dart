import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/market/data/models/economic_data_point.dart';
import 'package:app/features/market/data/providers/fred_economic_data_provider.dart';

void main() {
  test(
    'identifica correctamente el proveedor como FRED',
    () {
      final provider = FredEconomicDataProvider(
        apiKey: 'test-key',
      );

      expect(provider.providerId, 'fred');

      provider.dispose();
    },
  );

  test(
    'convierte correctamente las observaciones de FRED',
    () async {
      final client = MockClient((request) async {
        expect(
          request.url.path,
          '/fred/series/observations',
        );

        expect(
          request.url.queryParameters['series_id'],
          'DGS10',
        );

        expect(
          request.url.queryParameters['api_key'],
          'test-key',
        );

        return http.Response(
          jsonEncode({
            'observations': [
              {
                'date': '2026-08-25',
                'value': '4.28',
              },
              {
                'date': '2026-08-26',
                'value': '4.31',
              },
            ],
          }),
          200,
        );
      });

      final provider = FredEconomicDataProvider(
        apiKey: 'test-key',
        client: client,
      );

      final result = await provider.getSeries('DGS10');

      expect(result, hasLength(2));
      expect(result[0], isA<EconomicDataPoint>());

      expect(result[0].seriesId, 'DGS10');
      expect(result[0].value, 4.28);
      expect(
        result[0].timestamp,
        DateTime(2026, 8, 25),
      );
      expect(result[0].providerId, 'fred');

      expect(result[1].seriesId, 'DGS10');
      expect(result[1].value, 4.31);
      expect(
        result[1].timestamp,
        DateTime(2026, 8, 26),
      );

      provider.dispose();
    },
  );

  test(
    'normaliza el identificador de serie',
    () async {
      final client = MockClient((request) async {
        expect(
          request.url.queryParameters['series_id'],
          'DGS10',
        );

        return http.Response(
          jsonEncode({
            'observations': [
              {
                'date': '2026-08-26',
                'value': '4.31',
              },
            ],
          }),
          200,
        );
      });

      final provider = FredEconomicDataProvider(
        apiKey: 'test-key',
        client: client,
      );

      final result = await provider.getSeries('  dgs10  ');

      expect(result, hasLength(1));
      expect(result.first.seriesId, 'DGS10');

      provider.dispose();
    },
  );

  test(
    'ignora observaciones con valores no numéricos',
    () async {
      final client = MockClient((request) async {
        return http.Response(
          jsonEncode({
            'observations': [
              {
                'date': '2026-08-25',
                'value': '4.28',
              },
              {
                'date': '2026-08-26',
                'value': '.',
              },
              {
                'date': '2026-08-27',
                'value': 'N/A',
              },
              {
                'date': '2026-08-28',
                'value': '4.35',
              },
            ],
          }),
          200,
        );
      });

      final provider = FredEconomicDataProvider(
        apiKey: 'test-key',
        client: client,
      );

      final result = await provider.getSeries('DGS10');

      expect(result, hasLength(2));
      expect(result[0].value, 4.28);
      expect(result[1].value, 4.35);

      provider.dispose();
    },
  );

  test(
    'lanza ArgumentError para una serie vacía',
    () async {
      final provider = FredEconomicDataProvider(
        apiKey: 'test-key',
      );

      expect(
        provider.getSeries('   '),
        throwsArgumentError,
      );

      provider.dispose();
    },
  );

  test(
    'lanza FormatException ante una respuesta JSON inesperada',
    () async {
      final client = MockClient((request) async {
        return http.Response(
          jsonEncode({
            'unexpected': true,
          }),
          200,
        );
      });

      final provider = FredEconomicDataProvider(
        apiKey: 'test-key',
        client: client,
      );

      expect(
        provider.getSeries('DGS10'),
        throwsFormatException,
      );

      provider.dispose();
    },
  );
}
