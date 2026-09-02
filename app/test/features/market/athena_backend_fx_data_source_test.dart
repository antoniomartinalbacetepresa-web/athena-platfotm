import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/market/data/datasources/athena_backend_fx_data_source.dart';

void main() {
  group('AthenaBackendFxDataSource', () {
    test('obtiene FX actual con par y provenance verificables', () async {
      final client = MockClient((request) async {
        expect(request.url.path, '/api/v1/market/fx/quote');
        expect(request.url.queryParameters['base'], 'USD');
        expect(request.url.queryParameters['quote'], 'EUR');

        return http.Response(
          jsonEncode({
            'data': {
              'status': 'fx_current_ready',
              'baseCurrency': 'USD',
              'quoteCurrency': 'EUR',
              'rate': 0.86,
              'observedAt': '2026-09-02T22:00:00Z',
              'retrievedAt': '2026-09-02T22:00:02Z',
              'sourceProvider': 'yahoo',
              'sourceSymbol': 'USDEUR=X',
              'historicalPointInTimeEligible': false,
            },
          }),
          200,
        );
      });

      final dataSource = AthenaBackendFxDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final quote = await dataSource.getCurrentRate(
        baseCurrency: ' usd ',
        quoteCurrency: 'eur',
      );

      expect(quote.baseCurrency, 'USD');
      expect(quote.quoteCurrency, 'EUR');
      expect(quote.rate, 0.86);
      expect(quote.sourceProvider, 'yahoo');
      expect(quote.sourceSymbol, 'USDEUR=X');
      expect(quote.historicalPointInTimeEligible, isFalse);
      expect(quote.convertCurrent(100), 86);
    });

    test('rechaza respuesta de un par distinto', () async {
      final client = MockClient((request) async => http.Response(
            jsonEncode({
              'data': {
                'status': 'fx_current_ready',
                'baseCurrency': 'GBP',
                'quoteCurrency': 'EUR',
                'rate': 1.1,
                'observedAt': '2026-09-02T22:00:00Z',
                'retrievedAt': '2026-09-02T22:00:02Z',
                'sourceProvider': 'yahoo',
                'sourceSymbol': 'GBPEUR=X',
                'historicalPointInTimeEligible': false,
              },
            }),
            200,
          ));

      final dataSource = AthenaBackendFxDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      expect(
        () => dataSource.getCurrentRate(
          baseCurrency: 'USD',
          quoteCurrency: 'EUR',
        ),
        throwsA(isA<FormatException>()),
      );
    });

    test('rechaza tasa no finita o no positiva', () {
      final invalidPayloads = [0.0, -1.0, double.infinity, double.nan];

      for (final rate in invalidPayloads) {
        expect(
          () => AthenaBackendFxDataSource(
            baseUrl: 'https://api.athena.test',
            client: MockClient((request) async => http.Response(
                  jsonEncode({
                    'data': {
                      'status': 'fx_current_ready',
                      'baseCurrency': 'USD',
                      'quoteCurrency': 'EUR',
                      'rate': rate,
                      'observedAt': '2026-09-02T22:00:00Z',
                      'retrievedAt': '2026-09-02T22:00:02Z',
                      'sourceProvider': 'yahoo',
                      'sourceSymbol': 'USDEUR=X',
                      'historicalPointInTimeEligible': false,
                    },
                  }),
                  200,
                )),
          ).getCurrentRate(baseCurrency: 'USD', quoteCurrency: 'EUR'),
          throwsA(anything),
        );
      }
    });

    test('rechaza contrato actual marcado como PIT histórico', () async {
      final client = MockClient((request) async => http.Response(
            jsonEncode({
              'data': {
                'status': 'fx_current_ready',
                'baseCurrency': 'USD',
                'quoteCurrency': 'EUR',
                'rate': 0.86,
                'observedAt': '2026-09-02T22:00:00Z',
                'retrievedAt': '2026-09-02T22:00:02Z',
                'sourceProvider': 'yahoo',
                'sourceSymbol': 'USDEUR=X',
                'historicalPointInTimeEligible': true,
              },
            }),
            200,
          ));

      final dataSource = AthenaBackendFxDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      expect(
        () => dataSource.getCurrentRate(
          baseCurrency: 'USD',
          quoteCurrency: 'EUR',
        ),
        throwsA(isA<ArgumentError>()),
      );
    });

    test('admite identidad sólo con tasa uno y sin símbolo de mercado', () async {
      final client = MockClient((request) async => http.Response(
            jsonEncode({
              'data': {
                'status': 'fx_identity',
                'baseCurrency': 'EUR',
                'quoteCurrency': 'EUR',
                'rate': 1.0,
                'observedAt': '2026-09-02T22:00:00Z',
                'retrievedAt': '2026-09-02T22:00:00Z',
                'sourceProvider': 'identity',
                'sourceSymbol': null,
                'historicalPointInTimeEligible': false,
              },
            }),
            200,
          ));

      final dataSource = AthenaBackendFxDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final quote = await dataSource.getCurrentRate(
        baseCurrency: 'EUR',
        quoteCurrency: 'EUR',
      );

      expect(quote.isIdentity, isTrue);
      expect(quote.rate, 1.0);
    });
  });
}
