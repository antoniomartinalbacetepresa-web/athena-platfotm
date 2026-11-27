import 'dart:convert';

import 'package:app/features/market/data/providers/athena_backend_market_data_provider.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

// All prices and provider identifiers below are synthetic fixtures.
final observed = DateTime.utc(2026, 11, 23, 21);
final retrieved = DateTime.utc(2026, 11, 24, 10);

Map<String, dynamic> payload() => {
  'data': [
    {
      'observationId': 17, 'instrumentId': 7, 'symbol': 'SYNTH',
      'canonicalIdentityStatus': 'matched_internal_listing',
      'timestamp': observed.toIso8601String(),
      'retrievedAt': retrieved.toIso8601String(),
      'availableAt': retrieved.toIso8601String(), 'sourceTimestamp': null,
      'sourceProvider': 'synthetic_fixture', 'currency': 'USD',
      'open': 99, 'high': 103, 'low': 98, 'close': 101, 'volume': 200,
      'historicalPointInTimeEligible': false, 'realTimePriceVerified': false,
    },
  ],
  'provenance': {
    'retrievalMode': 'persisted_local_history', 'instrumentId': 7,
    'sourceProvider': 'synthetic_fixture', 'asOf': retrieved.toIso8601String(),
    'observedFrom': observed.toIso8601String(),
    'observedTo': observed.toIso8601String(),
    'licenceVerified': false, 'historicalPointInTimeEligible': false,
    'productionCoverageClaimed': false, 'orderExecutionAllowed': false,
    'researchOnly': true, 'truncated': false,
  },
};

void main() {
  Future<dynamic> fetch(http.Client client) => AthenaBackendMarketDataProvider(
    baseUrl: 'https://api.athena.test', client: client,
  ).getPersistedHistoricalData(
    instrumentId: 7, symbol: 'SYNTH', sourceProvider: 'synthetic_fixture',
    observedFrom: observed, observedTo: observed, asOf: retrieved,
  );

  test('reads exact local selection and retains immutable provenance', () async {
    final result = await fetch(MockClient((request) async {
      expect(request.url.path, '/api/v1/market/history/persisted');
      expect(request.url.queryParameters, {
        'instrumentId': '7', 'sourceProvider': 'synthetic_fixture',
        'observedFrom': observed.toIso8601String(),
        'observedTo': observed.toIso8601String(),
        'asOf': retrieved.toIso8601String(), 'limit': '400',
      });
      return http.Response(jsonEncode(payload()), 200);
    }));
    expect(result.points.single.close, 101);
    expect(result.points.single.volume, 200);
    expect(result.points.single.observationId, 17);
    expect(result.points.single.availableAt, retrieved);
    expect(result.points.single.sourceTimestamp, isNull);
    expect(result.points.single.historicalPointInTimeEligible, isFalse);
    expect(result.truncated, isFalse);
    expect(() => result.points.clear(), throwsUnsupportedError);
  });

  for (final field in ['licenceVerified', 'historicalPointInTimeEligible',
    'productionCoverageClaimed', 'orderExecutionAllowed']) {
    test('rejects authority escalation in $field', () async {
      final body = payload();
      body['provenance'][field] = true;
      await expectLater(fetch(MockClient((_) async =>
        http.Response(jsonEncode(body), 200))), throwsFormatException);
    });
  }

  for (final change in <String, dynamic>{
    'instrumentId': 8, 'sourceProvider': 'synthetic_other',
    'symbol': 'OTHER', 'observationId': '17', 'close': null,
    'retrievedAt': '2026-11-24T10:00:00.000001Z',
    'availableAt': '2026-11-23T21:00:00Z',
    'sourceTimestamp': '2026-11-24T10:00:00.000001Z',
    'historicalPointInTimeEligible': true,
  }.entries) {
    test('rejects incompatible persisted ${change.key}', () async {
      final body = payload();
      body['data'][0][change.key] = change.value;
      await expectLater(fetch(MockClient((_) async =>
        http.Response(jsonEncode(body), 200))), throwsFormatException);
    });
  }

  test('rejects duplicate observations and unordered history', () async {
    final body = payload();
    body['data'].add(Map<String, dynamic>.from(body['data'][0] as Map));
    await expectLater(fetch(MockClient((_) async =>
      http.Response(jsonEncode(body), 200))), throwsFormatException);
  });

  test('preserves explicit truncation and empty local results', () async {
    final body = payload();
    body['data'] = [];
    body['provenance']['truncated'] = true;
    final result = await fetch(MockClient((_) async =>
      http.Response(jsonEncode(body), 200)));
    expect(result.points, isEmpty);
    expect(result.truncated, isTrue);
  });

  test('does not fall back to a provider after storage failure', () async {
    var calls = 0;
    await expectLater(fetch(MockClient((request) async {
      calls++;
      expect(request.url.path, '/api/v1/market/history/persisted');
      return http.Response('storage unavailable', 503);
    })), throwsException);
    expect(calls, 1);
  });
}
