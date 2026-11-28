import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/market/data/providers/athena_backend_market_data_provider.dart';

void main() {
  Future<void> expectObservation({
    required String observation,
    required String retrieval,
    required bool accepted,
  }) async {
    final provider = AthenaBackendMarketDataProvider(
      baseUrl: 'https://api.athena.test',
      client: MockClient((_) async => http.Response(
        jsonEncode({
          'data': {
            'symbol': 'MSFT',
            'timestamp': observation,
            'retrievedAt': retrieval,
            'close': 400.0,
          },
        }),
        200,
      )),
    );
    try {
      if (accepted) {
        final point = await provider.getQuote('MSFT');
        expect(point?.close, 400.0);
      } else {
        await expectLater(provider.getQuote('MSFT'), throwsFormatException);
      }
    } finally {
      provider.dispose();
    }
  }

  test('future observation relative to retrieval fails closed', () async {
    await expectObservation(
      observation: '2026-11-13T12:00:01Z',
      retrieval: '2026-11-13T12:00:00Z',
      accepted: false,
    );
  });

  test('same instant and historical observation are permitted', () async {
    await expectObservation(
      observation: '2026-11-13T12:00:00Z',
      retrieval: '2026-11-13T12:00:00Z',
      accepted: true,
    );
    await expectObservation(
      observation: '2026-11-12T21:00:00Z',
      retrieval: '2026-11-13T12:00:00Z',
      accepted: true,
    );
  });
}
