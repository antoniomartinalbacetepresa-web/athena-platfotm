import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/market/data/providers/athena_backend_market_data_provider.dart';

void main() {
  for (final field in [
    'realTimePriceVerified',
    'historicalPointInTimeEligible',
  ]) {
    test('Market rejects non-boolean $field instead of silently dropping it', () async {
      final provider = AthenaBackendMarketDataProvider(
        baseUrl: 'https://api.athena.test',
        client: MockClient((_) async => http.Response(
          jsonEncode({
            'data': {
              'symbol': 'MSFT',
              'timestamp': '2026-11-12T21:00:00Z',
              'close': 400.0,
              field: 'true',
            },
          }),
          200,
        )),
      );
      try {
        await expectLater(
          provider.getQuote('MSFT'),
          throwsA(isA<FormatException>().having(
            (error) => error.message,
            'message',
            contains(field),
          )),
        );
      } finally {
        provider.dispose();
      }
    });
  }
}
