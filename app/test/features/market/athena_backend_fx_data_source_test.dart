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

    test('obtiene FX histórico para una fecha exacta', () async {
      final client = MockClient((request) async {
        expect(request.url.path, '/api/v1/market/fx/historical');
        expect(request.url.queryParameters['base'], 'USD');
        expect(request.url.queryParameters['quote'], 'EUR');
        expect(request.url.queryParameters['observedOn'], '2026-08-15');
        expect(request.url.queryParameters.containsKey('knowledgeCutoff'), isFalse);

        return http.Response(
          jsonEncode({
            'data': {
              'status': 'fx_historical_ready',
              'baseCurrency': 'USD',
              'quoteCurrency': 'EUR',
              'rate': 0.84,
              'observedAt': '2026-08-15T00:00:00Z',
              'retrievedAt': '2026-09-04T18:00:00Z',
              'sourceProvider': 'yahoo',
              'sourceSymbol': 'USDEUR=X',
              'historicalPointInTimeEligible': true,
            },
          }),
          200,
        );
      });

      final dataSource = AthenaBackendFxDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final quote = await dataSource.getHistoricalRate(
        baseCurrency: 'USD',
        quoteCurrency: 'EUR',
        observedOn: DateTime.utc(2026, 8, 15),
      );

      expect(quote.rate, 0.84);
      expect(quote.historicalPointInTimeEligible, isTrue);
      expect(quote.observedAt, DateTime.utc(2026, 8, 15));
      expect(quote.retrievedAt, DateTime.utc(2026, 9, 4, 18));
    });

    test('rechaza histórico recuperado después del knowledge cutoff', () async {
      final client = MockClient((request) async => http.Response(
            jsonEncode({
              'data': {
                'status': 'fx_historical_ready',
                'baseCurrency': 'USD',
                'quoteCurrency': 'EUR',
                'rate': 0.84,
                'observedAt': '2026-08-15T00:00:00Z',
                'retrievedAt': '2026-09-04T18:00:00Z',
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
        () => dataSource.getHistoricalRate(
          baseCurrency: 'USD',
          quoteCurrency: 'EUR',
          observedOn: DateTime.utc(2026, 8, 15),
          knowledgeCutoff: DateTime.utc(2026, 8, 16),
        ),
        throwsA(isA<FormatException>()),
      );
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

    test('rechaza FMP y proveedores codificados desde el contrato HTTP FX', () async {
      for (final provider in ['FMP', 'Financial Modeling Prep', 'f%6dp', 'f&#109;p']) {
        final client = MockClient((request) async => http.Response(
              jsonEncode({
                'data': {
                  'status': 'fx_current_ready',
                  'baseCurrency': 'USD',
                  'quoteCurrency': 'EUR',
                  'rate': 0.86,
                  'observedAt': '2026-09-02T22:00:00Z',
                  'retrievedAt': '2026-09-02T22:00:02Z',
                  'sourceProvider': provider,
                  'sourceSymbol': 'USDEUR=X',
                  'historicalPointInTimeEligible': false,
                },
              }),
              200,
            ));
        final source = AthenaBackendFxDataSource(
          baseUrl: 'https://api.athena.test',
          client: client,
        );
        await expectLater(
          source.getCurrentRate(baseCurrency: 'USD', quoteCurrency: 'EUR'),
          throwsA(isA<ArgumentError>()),
        );
        source.dispose();
      }
    });

    test('rechaza histórico si el backend omite la elegibilidad PIT', () async {
      final client = MockClient((request) async => http.Response(
            jsonEncode({
              'data': {
                'status': 'fx_historical_ready',
                'baseCurrency': 'USD',
                'quoteCurrency': 'EUR',
                'rate': 0.84,
                'observedAt': '2026-08-15T00:00:00Z',
                'retrievedAt': '2026-08-16T00:00:00Z',
                'sourceProvider': 'yahoo',
                'sourceSymbol': 'USDEUR=X',
                'historicalPointInTimeEligible': false,
              },
            }),
            200,
          ));
      final source = AthenaBackendFxDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );
      await expectLater(
        source.getHistoricalRate(
          baseCurrency: 'USD',
          quoteCurrency: 'EUR',
          observedOn: DateTime.utc(2026, 8, 15),
        ),
        throwsA(isA<ArgumentError>()),
      );
      source.dispose();
    });

    test('rechaza una respuesta histórica en el endpoint de FX actual', () async {
      final client = MockClient((request) async => http.Response(
            jsonEncode({
              'data': {
                'status': 'fx_historical_ready',
                'baseCurrency': 'USD',
                'quoteCurrency': 'EUR',
                'rate': 0.84,
                'observedAt': '2026-08-15T00:00:00Z',
                'retrievedAt': '2026-08-16T00:00:00Z',
                'sourceProvider': 'yahoo',
                'sourceSymbol': 'USDEUR=X',
                'historicalPointInTimeEligible': true,
              },
            }),
            200,
          ));
      final source = AthenaBackendFxDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );
      await expectLater(
        source.getCurrentRate(baseCurrency: 'USD', quoteCurrency: 'EUR'),
        throwsA(isA<FormatException>()),
      );
      source.dispose();
    });

    test('identidad FX histórica no exige recuperación de mercado antes del corte', () async {
      final client = MockClient((request) async => http.Response(
            jsonEncode({
              'data': {
                'status': 'fx_historical_identity',
                'baseCurrency': 'EUR',
                'quoteCurrency': 'EUR',
                'rate': 1.0,
                'observedAt': '2026-08-15T00:00:00Z',
                'retrievedAt': '2026-09-04T18:00:00Z',
                'sourceProvider': 'identity',
                'sourceSymbol': null,
                'historicalPointInTimeEligible': true,
              },
            }),
            200,
          ));
      final source = AthenaBackendFxDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );
      final result = await source.getHistoricalRate(
        baseCurrency: 'EUR',
        quoteCurrency: 'EUR',
        observedOn: DateTime.utc(2026, 8, 15),
        knowledgeCutoff: DateTime.utc(2026, 8, 16),
      );
      expect(result.isIdentity, isTrue);
      expect(result.historicalPointInTimeEligible, isTrue);
      expect(result.rate, 1.0);
      source.dispose();
    });

    test('rechaza FX actual con marcas temporales futuras', () async {
      final client = MockClient((request) async => http.Response(
            jsonEncode({
              'data': {
                'status': 'fx_current_ready',
                'baseCurrency': 'USD',
                'quoteCurrency': 'EUR',
                'rate': 0.86,
                'observedAt': '2099-01-01T00:00:00Z',
                'retrievedAt': '2099-01-01T00:00:01Z',
                'sourceProvider': 'yahoo',
                'sourceSymbol': 'USDEUR=X',
                'historicalPointInTimeEligible': false,
              },
            }),
            200,
          ));
      final source = AthenaBackendFxDataSource(
        baseUrl: 'https://api.athena.test', client: client,
      );
      await expectLater(
        source.getCurrentRate(baseCurrency: 'USD', quoteCurrency: 'EUR'),
        throwsA(isA<FormatException>()),
      );
      source.dispose();
    });

    test('rechaza marcas FX sin zona horaria explícita', () async {
      final client = MockClient((request) async => http.Response(
            jsonEncode({
              'data': {
                'status': 'fx_current_ready',
                'baseCurrency': 'USD',
                'quoteCurrency': 'EUR',
                'rate': 0.86,
                'observedAt': '2026-09-02T22:00:00',
                'retrievedAt': '2026-09-02T22:00:02Z',
                'sourceProvider': 'yahoo',
                'sourceSymbol': 'USDEUR=X',
                'historicalPointInTimeEligible': false,
              },
            }),
            200,
          ));
      final source = AthenaBackendFxDataSource(
        baseUrl: 'https://api.athena.test', client: client,
      );
      await expectLater(
        source.getCurrentRate(baseCurrency: 'USD', quoteCurrency: 'EUR'),
        throwsA(isA<FormatException>()),
      );
      source.dispose();
    });

    test('rechaza identidad de proveedor en par FX de mercado', () async {
      final client = MockClient((request) async => http.Response(
            jsonEncode({
              'data': {
                'status': 'fx_current_ready',
                'baseCurrency': 'USD',
                'quoteCurrency': 'EUR',
                'rate': 0.86,
                'observedAt': '2026-09-02T22:00:00Z',
                'retrievedAt': '2026-09-02T22:00:02Z',
                'sourceProvider': 'identity',
                'sourceSymbol': 'USDEUR=X',
                'historicalPointInTimeEligible': false,
              },
            }),
            200,
          ));
      final source = AthenaBackendFxDataSource(
        baseUrl: 'https://api.athena.test', client: client,
      );
      await expectLater(
        source.getCurrentRate(baseCurrency: 'USD', quoteCurrency: 'EUR'),
        throwsA(isA<ArgumentError>()),
      );
      source.dispose();
    });

    test('rechaza FX histórico recuperado en el futuro sin cutoff', () async {
      final client = MockClient((request) async => http.Response(
            jsonEncode({
              'data': {
                'status': 'fx_historical_ready',
                'baseCurrency': 'USD',
                'quoteCurrency': 'EUR',
                'rate': 0.86,
                'observedAt': '2026-08-15T00:00:00Z',
                'retrievedAt': '2099-01-01T00:00:00Z',
                'sourceProvider': 'yahoo',
                'sourceSymbol': 'USDEUR=X',
                'historicalPointInTimeEligible': true,
              },
            }),
            200,
          ));
      final source = AthenaBackendFxDataSource(
        baseUrl: 'https://api.athena.test', client: client,
      );
      await expectLater(
        source.getHistoricalRate(
          baseCurrency: 'USD', quoteCurrency: 'EUR',
          observedOn: DateTime.utc(2026, 8, 15),
        ),
        throwsA(isA<FormatException>()),
      );
      source.dispose();
    });

    test('rechaza identidad histórica observada después del cutoff', () async {
      final client = MockClient((request) async => http.Response(
            jsonEncode({
              'data': {
                'status': 'fx_historical_identity',
                'baseCurrency': 'EUR',
                'quoteCurrency': 'EUR',
                'rate': 1.0,
                'observedAt': '2026-08-15T12:00:00Z',
                'retrievedAt': '2026-09-04T18:00:00Z',
                'sourceProvider': 'identity',
                'sourceSymbol': null,
                'historicalPointInTimeEligible': true,
              },
            }),
            200,
          ));
      final source = AthenaBackendFxDataSource(
        baseUrl: 'https://api.athena.test', client: client,
      );
      await expectLater(
        source.getHistoricalRate(
          baseCurrency: 'EUR', quoteCurrency: 'EUR',
          observedOn: DateTime.utc(2026, 8, 15),
          knowledgeCutoff: DateTime.utc(2026, 8, 15),
        ),
        throwsA(isA<FormatException>()),
      );
      source.dispose();
    });

    test('rechaza knowledge cutoff futuro antes de consultar al backend', () async {
      final client = MockClient((request) async {
        throw StateError('No debe consultar el backend con un cutoff futuro.');
      });
      final source = AthenaBackendFxDataSource(
        baseUrl: 'https://api.athena.test', client: client,
      );
      await expectLater(
        source.getHistoricalRate(
          baseCurrency: 'USD', quoteCurrency: 'EUR',
          observedOn: DateTime.utc(2026, 8, 15),
          knowledgeCutoff: DateTime.utc(2099, 1, 1),
        ),
        throwsA(isA<ArgumentError>()),
      );
      source.dispose();
    });

    test('mantiene la fecha civil de observedOn en el contrato HTTP', () async {
      final localDay = DateTime(2026, 8, 15);
      final client = MockClient((request) async {
        expect(request.url.queryParameters['observedOn'], '2026-08-15');
        return http.Response(
          jsonEncode({
            'data': {
              'status': 'fx_historical_ready',
              'baseCurrency': 'USD',
              'quoteCurrency': 'EUR',
              'rate': 0.84,
              'observedAt': '2026-08-15T00:00:00Z',
              'retrievedAt': '2026-09-04T18:00:00Z',
              'sourceProvider': 'yahoo',
              'sourceSymbol': 'USDEUR=X',
              'historicalPointInTimeEligible': true,
            },
          }),
          200,
        );
      });
      final source = AthenaBackendFxDataSource(
        baseUrl: 'https://api.athena.test', client: client,
      );
      final quote = await source.getHistoricalRate(
        baseCurrency: 'USD', quoteCurrency: 'EUR', observedOn: localDay,
      );
      expect(quote.observedAt, DateTime.utc(2026, 8, 15));
      source.dispose();
    });
  });
}
