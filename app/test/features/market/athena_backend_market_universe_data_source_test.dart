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
  });
}
