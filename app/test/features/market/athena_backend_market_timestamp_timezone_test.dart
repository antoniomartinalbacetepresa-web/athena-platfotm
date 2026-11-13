import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/market/data/providers/athena_backend_market_data_provider.dart';

void main() {
  Future<void> fetchQuote(Map<String, Object> quote) async {
    final provider = AthenaBackendMarketDataProvider(
      baseUrl: 'https://api.athena.test',
      client: MockClient((_) async => http.Response(jsonEncode({'data': quote}), 200)),
    );
    try {
      await provider.getQuote('MSFT');
    } finally {
      provider.dispose();
    }
  }

  Map<String, Object> quote(String observed, String retrieved) => {
    'symbol': 'MSFT',
    'timestamp': observed,
    'retrievedAt': retrieved,
    'close': 400.0,
  };

  test('rejects market observation without explicit timezone', () async {
    await expectLater(
      fetchQuote(quote('2026-11-12T21:00:00', '2026-11-13T10:00:00Z')),
      throwsFormatException,
    );
  });

  test('rejects retrieval timestamp without explicit timezone', () async {
    await expectLater(
      fetchQuote(quote('2026-11-12T21:00:00Z', '2026-11-13T10:00:00')),
      throwsFormatException,
    );
  });

  test('rejects impossible observation timezone offset', () async {
    await expectLater(
      fetchQuote(quote('2026-11-12T21:00:00+25:00', '2026-11-13T10:00:00Z')),
      throwsFormatException,
    );
  });

  test('rejects impossible retrieval timezone minutes', () async {
    await expectLater(
      fetchQuote(quote('2026-11-12T21:00:00Z', '2026-11-13T10:00:00+01:90')),
      throwsFormatException,
    );
  });

  test('accepts offset-aware timestamps with consistent PIT order', () async {
    await fetchQuote(quote('2026-11-12T22:00:00+01:00', '2026-11-13T10:00:00Z'));
  });
}
