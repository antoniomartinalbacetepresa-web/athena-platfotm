import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/market/data/datasources/athena_backend_market_universe_data_source.dart';
import 'package:app/features/market/models/market_instrument_type.dart';

void main() {
  group('AthenaBackendMarketUniverseDataSource', () {
    test('obtiene y normaliza el universo del backend', () async {
      final client = MockClient((request) async {
        expect(request.url.path, '/api/v1/market/universe');

        return http.Response(
          jsonEncode({
            'data': [
              {
                'symbol': 'aapl',
                'companyName': 'Apple Inc.',
                'marketCap': 3500000000000,
                'country': 'United States',
                'exchange': 'NASDAQ Global Select',
                'exchangeShortName': 'NMS',
                'regionKey': 'america',
                'issuerId': 'US0378331005',
                'instrumentId': 'AAPL-NMS',
                'instrumentType': 'common_stock',
                'isPrimaryListing': true,
                'sector': 'Technology',
                'industry': 'Consumer Electronics',
              },
            ],
          }),
          200,
        );
      });

      final dataSource = AthenaBackendMarketUniverseDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final universe = await dataSource.getUniverse();

      expect(universe.length, 1);

      final asset = universe.single;

      expect(asset.symbol, 'AAPL');
      expect(asset.companyName, 'Apple Inc.');
      expect(asset.marketCap, 3500000000000.0);
      expect(asset.country, 'United States');
      expect(asset.exchangeShortName, 'NMS');
      expect(asset.regionKey, 'america');
      expect(asset.issuerId, 'US0378331005');
      expect(asset.instrumentId, 'AAPL-NMS');
      expect(asset.instrumentType, MarketInstrumentType.commonStock);
      expect(asset.isPrimaryListing, isTrue);
      expect(asset.sector, 'Technology');
      expect(asset.industry, 'Consumer Electronics');
    });

    test('obtiene y normaliza el estado del universo', () async {
      final client = MockClient((request) async {
        expect(request.url.path, '/api/v1/market/universe/status');

        return http.Response(
          jsonEncode({
            'data': {
              'activeCount': 16192,
              'globallyUsableCount': 2999,
              'usableCoverage': 0.1852149209486166,
              'regionCounts': {
                'america': 581,
                'europe': 1427,
                'asia': 991,
              },
              'isGlobalReady': true,
              'usingFallback': false,
            },
          }),
          200,
        );
      });

      final dataSource = AthenaBackendMarketUniverseDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final status = await dataSource.getStatus();

      expect(status.activeCount, 16192);
      expect(status.globallyUsableCount, 2999);
      expect(status.americaCount, 581);
      expect(status.europeCount, 1427);
      expect(status.asiaCount, 991);
      expect(status.isGlobalReady, isTrue);
      expect(status.usingFallback, isFalse);
    });

    test('rechaza un estado del universo con estructura inválida', () async {
      final client = MockClient((request) async {
        return http.Response(jsonEncode({'data': []}), 200);
      });

      final dataSource = AthenaBackendMarketUniverseDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      expect(dataSource.getStatus, throwsFormatException);
    });

    test('elimina duplicados del mismo listado', () async {
      final client = MockClient((_) async {
        return http.Response(
          jsonEncode({
            'data': [
              {
                'symbol': 'AAPL',
                'companyName': 'Apple Inc.',
                'exchangeShortName': 'NMS',
                'marketCap': 3500000000000,
              },
              {
                'symbol': 'AAPL',
                'companyName': 'Apple Inc.',
                'exchangeShortName': 'NMS',
                'marketCap': 3600000000000,
              },
            ],
          }),
          200,
        );
      });

      final dataSource = AthenaBackendMarketUniverseDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final universe = await dataSource.getUniverse();

      expect(universe.length, 1);
      expect(universe.single.marketCap, 3600000000000.0);
    });

    test('conserva listados diferentes del mismo símbolo', () async {
      final client = MockClient((_) async {
        return http.Response(
          jsonEncode({
            'data': [
              {
                'symbol': 'TEST',
                'companyName': 'Test Company',
                'exchangeShortName': 'NMS',
              },
              {
                'symbol': 'TEST',
                'companyName': 'Test Company',
                'exchangeShortName': 'LSE',
              },
            ],
          }),
          200,
        );
      });

      final dataSource = AthenaBackendMarketUniverseDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final universe = await dataSource.getUniverse();

      expect(universe.length, 2);

      expect(
        universe.map((asset) => asset.listingKey),
        containsAll(['TEST@NMS', 'TEST@LSE']),
      );
    });

    test('ignora registros sin símbolo o nombre', () async {
      final client = MockClient((_) async {
        return http.Response(
          jsonEncode({
            'data': [
              {'symbol': '', 'companyName': 'Sin símbolo'},
              {'symbol': 'NONAME', 'companyName': ''},
              {'symbol': 'VALID', 'companyName': 'Valid Company'},
            ],
          }),
          200,
        );
      });

      final dataSource = AthenaBackendMarketUniverseDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final universe = await dataSource.getUniverse();

      expect(universe.length, 1);
      expect(universe.single.symbol, 'VALID');
    });

    test('mapea tipos de instrumento desconocidos como unknown', () async {
      final client = MockClient((_) async {
        return http.Response(
          jsonEncode({
            'data': [
              {
                'symbol': 'XYZ',
                'companyName': 'XYZ Company',
                'instrumentType': 'future_type_not_known',
              },
            ],
          }),
          200,
        );
      });

      final dataSource = AthenaBackendMarketUniverseDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final universe = await dataSource.getUniverse();

      expect(universe.single.instrumentType, MarketInstrumentType.unknown);
    });

    test('acepta booleanos normalizados por el backend', () async {
      final client = MockClient((_) async {
        return http.Response(
          jsonEncode({
            'data': [
              {
                'symbol': 'ONE',
                'companyName': 'One Company',
                'isPrimaryListing': 1,
              },
              {
                'symbol': 'ZERO',
                'companyName': 'Zero Company',
                'isPrimaryListing': 'false',
              },
            ],
          }),
          200,
        );
      });

      final dataSource = AthenaBackendMarketUniverseDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final universe = await dataSource.getUniverse();

      expect(universe[0].isPrimaryListing, isTrue);

      expect(universe[1].isPrimaryListing, isFalse);
    });

    test('devuelve una lista vacía cuando no existen datos', () async {
      final client = MockClient((_) async {
        return http.Response(jsonEncode({'data': []}), 200);
      });

      final dataSource = AthenaBackendMarketUniverseDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final universe = await dataSource.getUniverse();

      expect(universe, isEmpty);
    });

    test('rechaza una estructura de datos inválida', () async {
      final client = MockClient((_) async {
        return http.Response(
          jsonEncode({
            'data': {'symbol': 'AAPL'},
          }),
          200,
        );
      });

      final dataSource = AthenaBackendMarketUniverseDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      expect(dataSource.getUniverse, throwsFormatException);
    });

    test('rechaza una respuesta HTTP no válida', () async {
      final client = MockClient((_) async {
        return http.Response('Service unavailable', 503);
      });

      final dataSource = AthenaBackendMarketUniverseDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      expect(dataSource.getUniverse, throwsException);
    });
    test('universe and status time out and retry without stale evidence', () async {
      final staleUniverse = Completer<http.Response>();
      final staleStatus = Completer<http.Response>();
      var universeCalls = 0;
      var statusCalls = 0;
      final source = AthenaBackendMarketUniverseDataSource(
        baseUrl: 'https://api.athena.test',
        requestTimeout: const Duration(milliseconds: 20),
        client: MockClient((request) {
          if (request.url.path.endsWith('/status')) {
            statusCalls++;
            if (statusCalls == 1) return staleStatus.future;
            return Future.value(http.Response(jsonEncode({
              'data': {
                'activeCount': 1,
                'globallyUsableCount': 0,
                'isWeightingReady': false,
              },
            }), 200));
          }
          universeCalls++;
          if (universeCalls == 1) return staleUniverse.future;
          return Future.value(http.Response(jsonEncode({
            'data': [
              {'symbol': 'AAA', 'companyName': 'Verified listing'},
            ],
          }), 200));
        }),
      );
      await expectLater(source.getUniverse(), throwsA(isA<TimeoutException>()));
      await expectLater(source.getStatus(), throwsA(isA<TimeoutException>()));
      final recoveredUniverse = await source.getUniverse();
      final recoveredStatus = await source.getStatus();
      expect(universeCalls, 2);
      expect(statusCalls, 2);
      expect(recoveredUniverse.single.symbol, 'AAA');
      expect(recoveredStatus.isWeightingReady, isFalse);
      staleUniverse.complete(http.Response('{"data":[]}', 200));
      staleStatus.complete(http.Response('{"data":null}', 200));
      source.dispose();
    });

  });
}
