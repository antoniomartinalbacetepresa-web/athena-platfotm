import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/market/data/providers/athena_backend_market_data_provider.dart';

void main() {
  Future<List<dynamic>> fetchHistory(List<Map<String, Object>> observations) async {
    final provider = AthenaBackendMarketDataProvider(
      baseUrl: 'https://api.athena.test',
      client: MockClient((_) async => http.Response(
        jsonEncode({'data': observations}),
        200,
      )),
    );
    try {
      return await provider.getHistoricalData(symbol: 'MSFT');
    } finally {
      provider.dispose();
    }
  }

  Map<String, Object> bar(String timestamp) => {
    'symbol': 'MSFT',
    'timestamp': timestamp,
    'retrievedAt': '2026-11-13T12:00:00Z',
    'close': 400.0,
    'volume': 1000.0,
  };

  test('rejects repeated historical instants including timezone aliases', () async {
    await expectLater(
      fetchHistory([
        bar('2026-11-12T21:00:00Z'),
        bar('2026-11-12T22:00:00+01:00'),
      ]),
      throwsFormatException,
    );
  });

  test('accepts distinct historical instants without modifying order', () async {
    final history = await fetchHistory([
      bar('2026-11-12T21:00:00Z'),
      bar('2026-11-11T21:00:00Z'),
    ]);
    expect(history, hasLength(2));
  });
}
