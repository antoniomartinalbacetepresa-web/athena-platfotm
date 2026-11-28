import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/market/data/providers/athena_backend_market_data_provider.dart';

void main() {
  test('two daily bars for one calendar session fail closed', () async {
    final provider = AthenaBackendMarketDataProvider(
      baseUrl: 'https://api.athena.test',
      client: MockClient((_) async => http.Response(
        jsonEncode({
          'data': [
            {
              'symbol': 'MSFT',
              'timestamp': '2026-11-12T16:00:00Z',
              'close': 400.0,
              'volume': 100,
            },
            {
              'symbol': 'MSFT',
              'timestamp': '2026-11-12T21:00:00Z',
              'close': 401.0,
              'volume': 150,
            },
          ],
        }),
        200,
      )),
    );
    try {
      await expectLater(
        provider.getHistoricalData(symbol: 'MSFT'),
        throwsA(isA<FormatException>().having(
          (error) => error.message,
          'message',
          contains('misma sesión'),
        )),
      );
    } finally {
      provider.dispose();
    }
  });
}
