import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/market/data/providers/athena_backend_market_data_provider.dart';

void main() {
  group('AthenaBackendMarketDataProvider', () {
    test('obtiene una cotización normalizada desde el backend', () async {
      final client = MockClient((request) async {
        expect(request.url.path, '/api/v1/market/quote');

        expect(request.url.queryParameters['symbol'], 'AAPL');

        return http.Response(
          jsonEncode({
            'data': {
              'symbol': 'AAPL',
              'timestamp': '2026-08-29T15:30:00Z',
              'open': 230.0,
              'high': 235.0,
              'low': 228.0,
              'close': 234.5,
              'adjustedClose': 234.5,
              'volume': 50000000,
              'change': 4.5,
              'changePercentage': 1.96,
            },
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final provider = AthenaBackendMarketDataProvider(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final quote = await provider.getQuote(' aapl ');

      expect(quote, isNotNull);
      expect(quote!.symbol, 'AAPL');
      expect(quote.open, 230.0);
      expect(quote.high, 235.0);
      expect(quote.low, 228.0);
      expect(quote.close, 234.5);
      expect(quote.adjustedClose, 234.5);
      expect(quote.volume, 50000000);
      expect(quote.change, 4.5);
      expect(quote.changePercentage, 1.96);
      expect(quote.providerId, 'athena_backend');
    });

    test('obtiene histórico y envía correctamente el periodo', () async {
      final client = MockClient((request) async {
        expect(request.url.path, '/api/v1/market/history');

        expect(request.url.queryParameters['symbol'], 'MSFT');

        expect(request.url.queryParameters['from'], '2026-01-01');

        expect(request.url.queryParameters['to'], '2026-08-29');

        return http.Response(
          jsonEncode({
            'data': [
              {
                'symbol': 'MSFT',
                'timestamp': '2026-08-28T00:00:00Z',
                'open': 500.0,
                'high': 510.0,
                'low': 495.0,
                'close': 508.0,
                'adjustedClose': 508.0,
                'volume': 20000000,
              },
              {
                'symbol': 'MSFT',
                'timestamp': '2026-08-29T00:00:00Z',
                'open': 508.0,
                'high': 515.0,
                'low': 505.0,
                'close': 512.0,
                'adjustedClose': 512.0,
                'volume': 21000000,
              },
            ],
          }),
          200,
        );
      });

      final provider = AthenaBackendMarketDataProvider(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final history = await provider.getHistoricalData(
        symbol: 'msft',
        from: DateTime(2026, 1, 1),
        to: DateTime(2026, 8, 29),
      );

      expect(history.length, 2);

      expect(history.first.symbol, 'MSFT');

      expect(history.first.close, 508.0);

      expect(history.last.close, 512.0);

      expect(history.last.providerId, 'athena_backend');
    });

    test('devuelve null cuando el backend no dispone de cotización', () async {
      final client = MockClient(
        (_) async => http.Response(jsonEncode({'data': null}), 200),
      );

      final provider = AthenaBackendMarketDataProvider(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final quote = await provider.getQuote('UNKNOWN');

      expect(quote, isNull);
    });

    test('devuelve histórico vacío cuando no existen datos', () async {
      final client = MockClient(
        (_) async => http.Response(jsonEncode({'data': []}), 200),
      );

      final provider = AthenaBackendMarketDataProvider(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final history = await provider.getHistoricalData(symbol: 'AAPL');

      expect(history, isEmpty);
    });

    test('rechaza símbolos vacíos', () async {
      final provider = AthenaBackendMarketDataProvider(
        baseUrl: 'https://api.athena.test',
        client: MockClient((_) async => http.Response('{}', 200)),
      );

      expect(() => provider.getQuote('   '), throwsArgumentError);
    });

    test('propaga un error ante una respuesta HTTP no válida', () async {
      final provider = AthenaBackendMarketDataProvider(
        baseUrl: 'https://api.athena.test',
        client: MockClient(
          (_) async => http.Response('Service unavailable', 503),
        ),
      );

      expect(() => provider.getQuote('AAPL'), throwsException);
    });

    test('rechaza una respuesta JSON con estructura inválida', () async {
      final provider = AthenaBackendMarketDataProvider(
        baseUrl: 'https://api.athena.test',
        client: MockClient(
          (_) async => http.Response(
            jsonEncode([
              {'symbol': 'AAPL'},
            ]),
            200,
          ),
        ),
      );

      expect(() => provider.getQuote('AAPL'), throwsFormatException);
    });
  });
}
