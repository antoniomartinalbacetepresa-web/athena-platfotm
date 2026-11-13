import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/market/data/providers/athena_backend_market_data_provider.dart';
import 'package:app/features/market/services/athena_backend_market_service.dart';

void main() {
  test('adjusted-only history cannot masquerade as a current market quote', () async {
    final provider = AthenaBackendMarketDataProvider(
      baseUrl: 'https://api.athena.test',
      client: MockClient((_) async => http.Response(
        jsonEncode({
          'data': {
            'symbol': 'MSFT',
            'timestamp': '2026-11-12T21:00:00Z',
            'adjustedClose': 400.0,
            'sourceProvider': 'historical_provider',
          },
        }),
        200,
      )),
    );
    final service = AthenaBackendMarketService(provider: provider);
    await expectLater(
      service.getQuote('MSFT'),
      throwsA(isA<FormatException>().having(
        (error) => error.message,
        'message',
        contains('precio de cierre válido'),
      )),
    );
    provider.dispose();
  });

  test('unadjusted close remains the displayed price when both are present', () async {
    final provider = AthenaBackendMarketDataProvider(
      baseUrl: 'https://api.athena.test',
      client: MockClient((_) async => http.Response(
        jsonEncode({
          'data': {
            'symbol': 'MSFT',
            'timestamp': '2026-11-12T21:00:00Z',
            'close': 405.0,
            'adjustedClose': 400.0,
          },
        }),
        200,
      )),
    );
    final service = AthenaBackendMarketService(provider: provider);
    final quote = await service.getQuote('MSFT');
    expect(quote.currentPrice, 405.0);
    provider.dispose();
  });
}
