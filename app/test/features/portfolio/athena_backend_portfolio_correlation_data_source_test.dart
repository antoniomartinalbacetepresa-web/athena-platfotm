import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/portfolio/data/athena_backend_portfolio_correlation_data_source.dart';

Map<String, Object?> payload({
  int leftInstrumentId = 7,
  int rightInstrumentId = 9,
  String sourceProvider = 'yahoo',
  String knowledgeCutoff = '2026-09-04T18:00:00Z',
  int sampleCount = 20,
  Object correlation = 0.42,
  String latestRetrievedAt = '2026-09-04T17:59:00Z',
  String recommendationPolicy = 'no_advice',
  bool productionEligible = false,
  bool allocationInfluence = false,
  bool automaticTrading = false,
}) {
  return {
    'leftInstrumentId': leftInstrumentId,
    'rightInstrumentId': rightInstrumentId,
    'sourceProvider': sourceProvider,
    'knowledgeCutoff': knowledgeCutoff,
    'sampleCount': sampleCount,
    'correlation': correlation,
    'firstReturnDate': '2026-08-01',
    'lastReturnDate': '2026-09-01',
    'latestRetrievedAt': latestRetrievedAt,
    'priceField': 'adjusted_close',
    'alignmentPolicy': 'utc_calendar_date_intersection',
    'returnPolicy': 'simple_return_consecutive_observations_per_instrument',
    'recommendationPolicy': recommendationPolicy,
    'productionEligible': productionEligible,
    'allocationInfluence': allocationInfluence,
    'automaticTrading': automaticTrading,
  };
}

void main() {
  test('requests canonical ids and validates PIT provenance', () async {
    final client = MockClient((request) async {
      expect(request.url.path, '/api/v1/portfolio/correlation');
      expect(request.url.queryParameters['leftInstrumentId'], '7');
      expect(request.url.queryParameters['rightInstrumentId'], '9');
      expect(request.url.queryParameters['sourceProvider'], 'yahoo');
      expect(
        request.url.queryParameters['knowledgeCutoff'],
        '2026-09-04T18:00:00.000Z',
      );
      return http.Response(jsonEncode({'data': payload()}), 200);
    });
    final dataSource = AthenaBackendPortfolioCorrelationDataSource(
      baseUrl: 'https://api.athena.test',
      client: client,
    );

    final result = await dataSource.getPair(
      leftInstrumentId: 7,
      rightInstrumentId: 9,
      sourceProvider: 'yahoo',
      knowledgeCutoff: DateTime.utc(2026, 9, 4, 18),
    );

    expect(result.sampleCount, 20);
    expect(result.correlation, 0.42);
    expect(result.latestRetrievedAt, DateTime.utc(2026, 9, 4, 17, 59));
    expect(result.recommendationPolicy, 'no_advice');
    expect(result.productionEligible, isFalse);
    expect(result.allocationInfluence, isFalse);
    expect(result.automaticTrading, isFalse);
  });

  test('rejects lookahead evidence retrieved after cutoff', () async {
    final dataSource = AthenaBackendPortfolioCorrelationDataSource(
      baseUrl: 'https://api.athena.test',
      client: MockClient((request) async => http.Response(
            jsonEncode({
              'data': payload(
                latestRetrievedAt: '2026-09-04T18:00:01Z',
              ),
            }),
            200,
          )),
    );

    expect(
      () => dataSource.getPair(
        leftInstrumentId: 7,
        rightInstrumentId: 9,
        sourceProvider: 'yahoo',
        knowledgeCutoff: DateTime.utc(2026, 9, 4, 18),
      ),
      throwsA(isA<FormatException>()),
    );
  });

  test('rejects nonfinite or out-of-range correlations', () async {
    for (final value in <Object>[double.nan, double.infinity, 1.01, -1.01]) {
      final dataSource = AthenaBackendPortfolioCorrelationDataSource(
        baseUrl: 'https://api.athena.test',
        client: MockClient((request) async => http.Response(
              jsonEncode({'data': payload(correlation: value)}),
              200,
            )),
      );

      expect(
        () => dataSource.getPair(
          leftInstrumentId: 7,
          rightInstrumentId: 9,
          sourceProvider: 'yahoo',
          knowledgeCutoff: DateTime.utc(2026, 9, 4, 18),
        ),
        throwsA(anyOf(isA<FormatException>(), isA<UnsupportedError>())),
      );
    }
  });

  test('rejects contract that tries to influence advice or allocation', () async {
    for (final bad in [
      payload(recommendationPolicy: 'advice'),
      payload(productionEligible: true),
      payload(allocationInfluence: true),
      payload(automaticTrading: true),
    ]) {
      final dataSource = AthenaBackendPortfolioCorrelationDataSource(
        baseUrl: 'https://api.athena.test',
        client: MockClient((request) async => http.Response(
              jsonEncode({'data': bad}),
              200,
            )),
      );

      expect(
        () => dataSource.getPair(
          leftInstrumentId: 7,
          rightInstrumentId: 9,
          sourceProvider: 'yahoo',
          knowledgeCutoff: DateTime.utc(2026, 9, 4, 18),
        ),
        throwsA(isA<FormatException>()),
      );
    }
  });

  test('rejects response for different instrument ids or provider', () async {
    for (final bad in [
      payload(leftInstrumentId: 10),
      payload(sourceProvider: 'other'),
    ]) {
      final dataSource = AthenaBackendPortfolioCorrelationDataSource(
        baseUrl: 'https://api.athena.test',
        client: MockClient((request) async => http.Response(
              jsonEncode({'data': bad}),
              200,
            )),
      );

      expect(
        () => dataSource.getPair(
          leftInstrumentId: 7,
          rightInstrumentId: 9,
          sourceProvider: 'yahoo',
          knowledgeCutoff: DateTime.utc(2026, 9, 4, 18),
        ),
        throwsA(isA<FormatException>()),
      );
    }
  });
}
