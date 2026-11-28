import 'dart:convert';

import 'package:app/features/market/data/providers/athena_backend_market_data_provider.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  Map<String, Object> bar(String timestamp, String session) => {
    'symbol': 'MSFT',
    'timestamp': timestamp,
    'retrievedAt': '2026-11-17T12:00:00Z',
    'priceSessionDate': session,
    'close': 400.0,
  };

  Future<void> fetch(List<Map<String, Object>> bars, {DateTime? from}) async {
    final provider = AthenaBackendMarketDataProvider(
      baseUrl: 'https://api.athena.test',
      client: MockClient((_) async => http.Response(jsonEncode({'data': bars}), 200)),
    );
    try {
      await provider.getHistoricalData(
        symbol: 'MSFT',
        from: from ?? DateTime.utc(2026, 11, 12),
        to: DateTime.utc(2026, 11, 12),
      );
    } finally {
      provider.dispose();
    }
  }

  test('uses exchange session date for historical window, not UTC observation date', () async {
    await fetch([bar('2026-11-13T00:30:00Z', '2026-11-12')]);
  });

  test('rejects out-of-window exchange session despite in-window timestamp', () async {
    await expectLater(
      fetch([bar('2026-11-12T23:30:00Z', '2026-11-13')]),
      throwsFormatException,
    );
  });

  test('rejects duplicate exchange sessions with different observation instants', () async {
    await expectLater(
      fetch([
        bar('2026-11-12T20:00:00Z', '2026-11-12'),
        bar('2026-11-13T00:30:00Z', '2026-11-12'),
      ]),
      throwsFormatException,
    );
  });

  test('rejects reversed sessions even when UTC instants increase', () async {
    await expectLater(
      fetch([
        bar('2026-11-12T19:00:00Z', '2026-11-12'),
        bar('2026-11-12T20:00:00Z', '2026-11-11'),
      ], from: DateTime.utc(2026, 11, 11)),
      throwsFormatException,
    );
  });

  test('accepts increasing sessions with increasing UTC instants', () async {
    final provider = AthenaBackendMarketDataProvider(
      baseUrl: 'https://api.athena.test',
      client: MockClient((_) async => http.Response(jsonEncode({
        'data': [
          bar('2026-11-11T20:00:00Z', '2026-11-11'),
          bar('2026-11-12T20:00:00Z', '2026-11-12'),
        ],
      }), 200)),
    );
    try {
      final points = await provider.getHistoricalData(symbol: 'MSFT');
      expect(points, hasLength(2));
    } finally {
      provider.dispose();
    }
  });
}
