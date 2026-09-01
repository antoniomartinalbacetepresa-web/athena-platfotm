import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/market/data/models/market_data_point.dart';
import 'package:app/features/market/data/providers/twelve_data_provider.dart';

void main() {
  group('TwelveDataProvider', () {
    test('obtiene correctamente una cotización', () async {
      final client = MockClient((request) async {
        expect(request.method, 'GET');
        expect(request.url.path, '/quote');
        expect(request.url.queryParameters['symbol'], 'AAPL');
        expect(request.url.queryParameters['apikey'], 'test-key');

        return http.Response(
          jsonEncode({
            'symbol': 'AAPL',
            'datetime': '2026-08-28 15:30:00',
            'open': '228.10',
            'high': '230.50',
            'low': '227.80',
            'close': '229.75',
            'volume': '12345678',
          }),
          200,
        );
      });

      final provider = TwelveDataProvider(
        apiKey: 'test-key',
        client: client,
      );

      final result = await provider.getQuote('aapl');

      expect(result, isA<MarketDataPoint>());
      expect(result!.symbol, 'AAPL');
      expect(result.providerId, 'twelve_data');
      expect(result.open, 228.10);
      expect(result.high, 230.50);
      expect(result.low, 227.80);
      expect(result.close, 229.75);
      expect(result.adjustedClose, 229.75);
      expect(result.volume, 12345678);
      expect(
        result.timestamp,
        DateTime(2026, 8, 28, 15, 30),
      );

      provider.dispose();
    });

    test('obtiene correctamente datos históricos', () async {
      final client = MockClient((request) async {
        expect(request.method, 'GET');
        expect(request.url.path, '/time_series');
        expect(request.url.queryParameters['symbol'], 'AAPL');
        expect(request.url.queryParameters['interval'], '1day');
        expect(request.url.queryParameters['start_date'], '2026-01-01');
        expect(request.url.queryParameters['end_date'], '2026-01-03');
        expect(request.url.queryParameters['apikey'], 'test-key');

        return http.Response(
          jsonEncode({
            'meta': {
              'symbol': 'AAPL',
            },
            'values': [
              {
                'datetime': '2026-01-03',
                'open': '250.00',
                'high': '255.00',
                'low': '248.00',
                'close': '253.00',
                'volume': '1000000',
              },
              {
                'datetime': '2026-01-02',
                'open': '245.00',
                'high': '251.00',
                'low': '244.00',
                'close': '250.00',
                'volume': '900000',
              },
            ],
          }),
          200,
        );
      });

      final provider = TwelveDataProvider(
        apiKey: 'test-key',
        client: client,
      );

      final result = await provider.getHistoricalData(
        symbol: 'aapl',
        from: DateTime(2026, 1, 1),
        to: DateTime(2026, 1, 3),
      );

      expect(result, hasLength(2));

      expect(result[0].symbol, 'AAPL');
      expect(result[0].close, 253.00);
      expect(result[0].volume, 1000000);

      expect(result[1].symbol, 'AAPL');
      expect(result[1].close, 250.00);
      expect(result[1].volume, 900000);

      expect(result.every((point) {
        return point.providerId == 'twelve_data';
      }), isTrue);

      provider.dispose();
    });

    test('devuelve lista vacía cuando no existen valores históricos', () async {
      final client = MockClient((request) async {
        return http.Response(
          jsonEncode({
            'meta': {
              'symbol': 'AAPL',
            },
            'values': [],
          }),
          200,
        );
      });

      final provider = TwelveDataProvider(
        apiKey: 'test-key',
        client: client,
      );

      final result = await provider.getHistoricalData(
        symbol: 'AAPL',
      );

      expect(result, isEmpty);

      provider.dispose();
    });

    test('devuelve null cuando una cotización no contiene precio de cierre',
        () async {
      final client = MockClient((request) async {
        return http.Response(
          jsonEncode({
            'symbol': 'AAPL',
            'datetime': '2026-08-28 15:30:00',
          }),
          200,
        );
      });

      final provider = TwelveDataProvider(
        apiKey: 'test-key',
        client: client,
      );

      final result = await provider.getQuote('AAPL');

      expect(result, isNull);

      provider.dispose();
    });

    test('rechaza un símbolo vacío', () async {
      final client = MockClient((request) async {
        fail('No debería realizarse ninguna petición.');
      });

      final provider = TwelveDataProvider(
        apiKey: 'test-key',
        client: client,
      );

      expect(
        () => provider.getQuote('   '),
        throwsArgumentError,
      );

      provider.dispose();
    });

    test('lanza excepción ante un código HTTP distinto de 200', () async {
      final client = MockClient((request) async {
        return http.Response(
          '{"message":"Unauthorized"}',
          401,
        );
      });

      final provider = TwelveDataProvider(
        apiKey: 'test-key',
        client: client,
      );

      expect(
        provider.getQuote('AAPL'),
        throwsException,
      );

      provider.dispose();
    });

    test('lanza excepción ante un error comunicado por Twelve Data',
        () async {
      final client = MockClient((request) async {
        return http.Response(
          jsonEncode({
            'status': 'error',
            'code': 401,
            'message': 'Invalid API key',
          }),
          200,
        );
      });

      final provider = TwelveDataProvider(
        apiKey: 'test-key',
        client: client,
      );

      expect(
        provider.getQuote('AAPL'),
        throwsException,
      );

      provider.dispose();
    });

    test('lanza excepción ante JSON histórico con formato inesperado',
        () async {
      final client = MockClient((request) async {
        return http.Response(
          jsonEncode({
            'values': {
              'unexpected': true,
            },
          }),
          200,
        );
      });

      final provider = TwelveDataProvider(
        apiKey: 'test-key',
        client: client,
      );

      expect(
        provider.getHistoricalData(symbol: 'AAPL'),
        throwsFormatException,
      );

      provider.dispose();
    });
  });
}