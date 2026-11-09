import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/market/data/providers/athena_backend_market_data_provider.dart';

void main() {
  group('AthenaBackendMarketDataProvider', () {
    test('obtiene una cotización normalizada con provenance e identidad básica', () async {
      final client = MockClient((request) async {
        expect(request.url.path, '/api/v1/market/quote');
        expect(request.url.queryParameters['symbol'], 'AAPL');

        return http.Response(
          jsonEncode({
            'data': {
              'symbol': 'AAPL',
              'timestamp': '2026-08-29T15:30:00Z',
              'retrievedAt': '2026-08-29T15:30:02Z',
              'sourceProvider': 'yahoo',
              'quoteMode': 'provider_fast_info',
              'realTimePriceVerified': false,
              'historicalPointInTimeEligible': false,
              'currency': 'usd',
              'exchange': 'NMS',
              'quoteType': 'EQUITY',
              'instrumentId': 17,
              'canonicalIdentityStatus': 'matched_internal_listing',
              'exchangeTimezone': 'America/New_York',
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
      expect(quote.currency, 'USD');
      expect(quote.exchange, 'NMS');
      expect(quote.quoteType, 'EQUITY');
      expect(quote.instrumentId, 17);
      expect(quote.canonicalIdentityStatus, 'matched_internal_listing');
      expect(quote.exchangeTimezone, 'America/New_York');
      expect(quote.providerId, 'athena_backend');
      expect(quote.sourceProvider, 'yahoo');
      expect(quote.quoteMode, 'provider_fast_info');
      expect(quote.realTimePriceVerified, isFalse);
      expect(quote.historicalPointInTimeEligible, isFalse);
      expect(
        quote.retrievedAt,
        DateTime.parse('2026-08-29T15:30:02Z'),
      );
    });

    test('obtiene histórico y conserva provenance', () async {
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
                'retrievedAt': '2026-08-30T10:00:00Z',
                'sourceProvider': 'yahoo',
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
                'retrievedAt': '2026-08-30T10:00:00Z',
                'sourceProvider': 'yahoo',
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
      expect(history.last.sourceProvider, 'yahoo');
      expect(
        history.last.retrievedAt,
        DateTime.parse('2026-08-30T10:00:00Z'),
      );
    });

    test('mantiene compatibilidad si provenance no está disponible', () async {
      final client = MockClient((_) async {
        return http.Response(
          jsonEncode({
            'data': {
              'symbol': 'AAPL',
              'timestamp': '2026-08-29T15:30:00Z',
              'close': 234.5,
            },
          }),
          200,
        );
      });

      final provider = AthenaBackendMarketDataProvider(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final quote = await provider.getQuote('AAPL');

      expect(quote, isNotNull);
      expect(quote!.sourceProvider, isNull);
      expect(quote.retrievedAt, isNull);
      expect(quote.currency, isNull);
    });

    test('rechaza retrievedAt inválido cuando el backend lo declara', () async {
      final provider = AthenaBackendMarketDataProvider(
        baseUrl: 'https://api.athena.test',
        client: MockClient(
          (_) async => http.Response(
            jsonEncode({
              'data': {
                'symbol': 'AAPL',
                'timestamp': '2026-08-29T15:30:00Z',
                'retrievedAt': 'no-es-fecha',
                'sourceProvider': 'yahoo',
                'close': 234.5,
              },
            }),
            200,
          ),
        ),
      );

      expect(() => provider.getQuote('AAPL'), throwsFormatException);
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
    test('quote timeout fails closed and a later request recovers', () async {
      final stalled = Completer<http.Response>();
      var calls = 0;
      final provider = AthenaBackendMarketDataProvider(
        baseUrl: 'https://api.athena.test',
        requestTimeout: const Duration(milliseconds: 20),
        client: MockClient((_) {
          calls++;
          if (calls == 1) return stalled.future;
          return Future.value(http.Response(jsonEncode({
            'data': {
              'symbol': 'AAPL',
              'timestamp': '2026-10-27T11:00:00Z',
              'sourceProvider': 'yahoo',
              'close': 250.0,
            },
          }), 200));
        }),
      );
      await expectLater(provider.getQuote('AAPL'), throwsA(isA<TimeoutException>()));
      final recovered = await provider.getQuote('AAPL');
      expect(calls, 2);
      expect(recovered?.close, 250.0);
      expect(recovered?.sourceProvider, 'yahoo');
      stalled.complete(http.Response('{"data":null}', 200));
      provider.dispose();
    });

    test('historical request times out instead of hanging indefinitely', () async {
      final stalled = Completer<http.Response>();
      final provider = AthenaBackendMarketDataProvider(
        baseUrl: 'https://api.athena.test',
        requestTimeout: const Duration(milliseconds: 20),
        client: MockClient((_) => stalled.future),
      );
      await expectLater(
        provider.getHistoricalData(symbol: 'AAPL'),
        throwsA(isA<TimeoutException>()),
      );
      stalled.complete(http.Response('{"data":[]}', 200));
      provider.dispose();
    });


    test('preserves daily-close fallback session identity', () async {
      final provider = AthenaBackendMarketDataProvider(
        baseUrl: 'https://api.athena.test',
        client: MockClient((_) async => http.Response(jsonEncode({
          'data': {
            'symbol': 'AAPL',
            'timestamp': '2026-11-01T23:00:00Z',
            'retrievedAt': '2026-11-01T23:00:00Z',
            'sourceProvider': 'yahoo',
            'close': 250.0,
            'quoteMode': 'historical_daily_close_fallback',
            'priceSessionDate': '2026-10-30',
            'realTimePriceVerified': false,
            'historicalPointInTimeEligible': false,
          },
        }), 200)),
      );
      final point = await provider.getQuote('AAPL');
      expect(point?.quoteMode, 'historical_daily_close_fallback');
      expect(point?.priceSessionDate, '2026-10-30');
      expect(point?.realTimePriceVerified, isFalse);
      expect(point?.historicalPointInTimeEligible, isFalse);
      provider.dispose();
    });


    for (final invalid in <String, Object>{
      'close': 'NaN',
      'adjustedClose': '-1',
      'open': 'Infinity',
      'volume': '-2',
      'changePercentage': 'Infinity',
    }.entries) {
      test('rechaza dato financiero inválido: ${invalid.key}', () async {
        final provider = AthenaBackendMarketDataProvider(
          baseUrl: 'https://api.athena.test',
          client: MockClient((_) async => http.Response(jsonEncode({
            'data': {
              'symbol': 'AAPL',
              'timestamp': '2026-11-09T16:00:00Z',
              'close': 250.0,
              invalid.key: invalid.value,
            },
          }), 200)),
        );
        await expectLater(provider.getQuote('AAPL'), throwsFormatException);
        provider.dispose();
      });
    }

    test('rechaza volumen inválido en histórico antes de llegar al Radar', () async {
      final provider = AthenaBackendMarketDataProvider(
        baseUrl: 'https://api.athena.test',
        client: MockClient((_) async => http.Response(jsonEncode({
          'data': [{
            'symbol': 'AAPL',
            'timestamp': '2026-11-09T16:00:00Z',
            'close': 250.0,
            'volume': 'NaN',
          }],
        }), 200)),
      );
      await expectLater(
        provider.getHistoricalData(symbol: 'AAPL'),
        throwsFormatException,
      );
      provider.dispose();
    });

    test('rechaza cotización sin símbolo en lugar de inventar identidad', () async {
      final provider = AthenaBackendMarketDataProvider(
        baseUrl: 'https://api.athena.test',
        client: MockClient((_) async => http.Response(jsonEncode({
          'data': {
            'timestamp': '2026-10-30T20:00:00Z',
            'sourceProvider': 'yahoo',
            'close': 250.0,
          },
        }), 200)),
      );
      await expectLater(provider.getQuote('AAPL'), throwsFormatException);
      provider.dispose();
    });

    test('rechaza histórico de otra empresa aunque el endpoint responda 200', () async {
      final provider = AthenaBackendMarketDataProvider(
        baseUrl: 'https://api.athena.test',
        client: MockClient((_) async => http.Response(jsonEncode({
          'data': [{
            'symbol': 'MSFT',
            'timestamp': '2026-10-30T20:00:00Z',
            'sourceProvider': 'yahoo',
            'close': 250.0,
          }],
        }), 200)),
      );
      await expectLater(
        provider.getHistoricalData(symbol: 'AAPL'),
        throwsFormatException,
      );
      provider.dispose();
    });
  });
}
