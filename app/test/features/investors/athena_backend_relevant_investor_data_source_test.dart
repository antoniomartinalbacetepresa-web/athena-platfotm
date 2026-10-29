import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/investors/data/athena_backend_relevant_investor_data_source.dart';

Map<String, Object?> envelope({
  String advisoryStatus = 'no_advice',
  bool productionEligible = false,
  bool influence = false,
  bool automaticScoring = false,
  bool automaticTrading = false,
  String retrievedAt = '2026-09-04T20:00:00Z',
  Object? canonicalInstrumentId,
  bool identityResolved = false,
  Object? ticker,
}) {
  return {
    'data': {
      'status': 'sec_13f_information_table_parsed',
      'form': '13F-HR',
      'accessionNumber': '0000123456-26-000001',
      'positionDate': '2026-06-30',
      'filingDate': '2026-08-14',
      'publicationDateTime': '2026-08-14T20:30:00Z',
      'retrievedAt': retrievedAt,
      'sourceUrl':
          'https://www.sec.gov/Archives/edgar/data/123456/000012345626000001/table.xml',
      'sourceProvider': 'SEC EDGAR',
      'valueUnit': 'thousands_usd_as_reported_by_sec_13f',
      'holdingCount': 1,
      'holdings': [
        {
          'cusip': '037833100',
          'issuerName': 'APPLE INC',
          'titleOfClass': 'COM',
          'valueThousandsUsd': 123456,
          'shareOrPrincipalAmount': 500000,
          'shareOrPrincipalType': 'SH',
          'putCall': null,
          'investmentDiscretion': 'SOLE',
          'otherManager': null,
          'votingAuthority': {'sole': 500000, 'shared': 0, 'none': 0},
          'canonicalInstrumentId': canonicalInstrumentId,
          'ticker': ticker,
          'identityResolved': identityResolved,
        },
      ],
      'identityPolicy': {
        'identifier': 'cusip_as_reported',
        'canonicalInstrumentResolved': false,
        'tickerResolution': 'disabled_until_authoritative_identity_evidence',
        'isWeightingReady': false,
      },
      'advisoryStatus': advisoryStatus,
      'productionEligible': productionEligible,
      'athenaRecommendationInfluence': influence,
      'automaticScoring': automaticScoring,
      'automaticTrading': automaticTrading,
      'accessionIndexUrl':
          'https://www.sec.gov/Archives/edgar/data/123456/000012345626000001/index.json',
      'documentSelectionPolicy':
          'official_accession_index_then_unique_information_table_xml',
    },
    'selectedFiling': {
      'form': '13F-HR',
      'accessionNumber': '0000123456-26-000001',
      'reportDate': '2026-06-30',
      'filingDate': '2026-08-14',
      'acceptanceDateTime': '20260814203000',
    },
  };
}

void main() {
  test('loads real SEC 13F evidence with three temporal references', () async {
    final client = MockClient((request) async {
      expect(request.url.path, '/api/v1/sec/institutional-holdings/latest');
      expect(request.url.queryParameters['cik'], '123456');
      return http.Response(jsonEncode(envelope()), 200);
    });
    final dataSource = AthenaBackendRelevantInvestorDataSource(
      baseUrl: 'https://api.athena.test',
      client: client,
    );

    final activity = await dataSource.getLatestInstitutionalHoldings(cik: '123456');

    expect(activity.cik, '123456');
    expect(activity.positionDate, DateTime.utc(2026, 6, 30));
    expect(activity.filingDate, DateTime.utc(2026, 8, 14));
    expect(activity.publicationDateTime, DateTime.utc(2026, 8, 14, 20, 30));
    expect(activity.retrievedAt, DateTime.utc(2026, 9, 4, 20));
    expect(activity.holdings.single.cusip, '037833100');
    expect(activity.holdings.single.issuerName, 'APPLE INC');
    expect(activity.recommendationPolicy, 'no_advice');
    expect(activity.productionEligible, isFalse);
    expect(activity.athenaRecommendationInfluence, isFalse);
    expect(activity.automaticScoring, isFalse);
    expect(activity.automaticTrading, isFalse);
    expect(activity.isWeightingReady, isFalse);
  });

  test('rejects retrieval before SEC publication', () async {
    final dataSource = AthenaBackendRelevantInvestorDataSource(
      baseUrl: 'https://api.athena.test',
      client: MockClient((request) async => http.Response(
            jsonEncode(envelope(retrievedAt: '2026-08-14T20:29:59Z')),
            200,
          )),
    );

    expect(
      () => dataSource.getLatestInstitutionalHoldings(cik: '123456'),
      throwsA(isA<FormatException>()),
    );
  });

  test('rejects any hidden ATHENA score or trading influence', () async {
    final badPayloads = [
      envelope(advisoryStatus: 'advice'),
      envelope(productionEligible: true),
      envelope(influence: true),
      envelope(automaticScoring: true),
      envelope(automaticTrading: true),
    ];

    for (final bad in badPayloads) {
      final dataSource = AthenaBackendRelevantInvestorDataSource(
        baseUrl: 'https://api.athena.test',
        client: MockClient(
          (request) async => http.Response(jsonEncode(bad), 200),
        ),
      );
      expect(
        () => dataSource.getLatestInstitutionalHoldings(cik: '123456'),
        throwsA(isA<FormatException>()),
      );
    }
  });

  test('rejects invented ticker or canonical identity in 13F evidence', () async {
    for (final bad in [
      envelope(ticker: 'AAPL'),
      envelope(canonicalInstrumentId: 'AAPL@NASDAQ'),
      envelope(identityResolved: true),
    ]) {
      final dataSource = AthenaBackendRelevantInvestorDataSource(
        baseUrl: 'https://api.athena.test',
        client: MockClient(
          (request) async => http.Response(jsonEncode(bad), 200),
        ),
      );
      expect(
        () => dataSource.getLatestInstitutionalHoldings(cik: '123456'),
        throwsA(isA<FormatException>()),
      );
    }
  });

  test('validates CIK locally and handles missing 13F as unavailable', () async {
    final dataSource = AthenaBackendRelevantInvestorDataSource(
      baseUrl: 'https://api.athena.test',
      client: MockClient((request) async => http.Response('{}', 404)),
    );

    expect(
      () => dataSource.getLatestInstitutionalHoldings(cik: 'ABC'),
      throwsArgumentError,
    );
    expect(
      () => dataSource.getLatestInstitutionalHoldings(cik: '123456'),
      throwsStateError,
    );
  });
  test('rejects a selected SEC acceptance inconsistent with PIT publication',
      () async {
    for (final acceptance in [
      '20260814203001',
      '20260814202959',
      '20260815203000',
      'not-a-timestamp',
      null,
    ]) {
      final payload = envelope();
      (payload['selectedFiling'] as Map<String, Object?>)['acceptanceDateTime'] =
          acceptance;
      final source = AthenaBackendRelevantInvestorDataSource(
        baseUrl: 'https://api.athena.test',
        client: MockClient((_) async => http.Response(jsonEncode(payload), 200)),
      );
      await expectLater(
        source.getLatestInstitutionalHoldings(cik: '123456'),
        throwsA(isA<FormatException>()),
      );
      source.dispose();
    }
  });

  test('rejects SEC documents belonging to another filer or accession',
      () async {
    for (final url in [
      'https://www.sec.gov/Archives/edgar/data/999999/000012345626000001/table.xml',
      'https://www.sec.gov/Archives/edgar/data/123456/000012345626000002/table.xml',
      'https://www.sec.gov/Archives/edgar/data/123456/000012345626000001/other/table.xml',
    ]) {
      final payload = envelope();
      (payload['data'] as Map<String, Object?>)['sourceUrl'] = url;
      final source = AthenaBackendRelevantInvestorDataSource(
        baseUrl: 'https://api.athena.test',
        client: MockClient((_) async => http.Response(jsonEncode(payload), 200)),
      );
      expect(
        () => source.getLatestInstitutionalHoldings(cik: '123456'),
        throwsA(isA<FormatException>()),
      );
    }
  });

  test('rejects mismatched accession index or unapproved selection policy',
      () async {
    for (final indexUrl in [
      'https://www.sec.gov/Archives/edgar/data/999999/000012345626000001/index.json',
      'https://www.sec.gov/Archives/edgar/data/123456/000012345626000002/index.json',
    ]) {
      final payload = envelope();
      (payload['data'] as Map<String, Object?>)['accessionIndexUrl'] = indexUrl;
      final source = AthenaBackendRelevantInvestorDataSource(
        baseUrl: 'https://api.athena.test',
        client: MockClient((_) async => http.Response(jsonEncode(payload), 200)),
      );
      expect(
        () => source.getLatestInstitutionalHoldings(cik: '123456'),
        throwsA(isA<FormatException>()),
      );
    }
    final payload = envelope();
    (payload['data'] as Map<String, Object?>)['documentSelectionPolicy'] =
        'first_xml_without_index';
    final source = AthenaBackendRelevantInvestorDataSource(
      baseUrl: 'https://api.athena.test',
      client: MockClient((_) async => http.Response(jsonEncode(payload), 200)),
    );
    expect(
      () => source.getLatestInstitutionalHoldings(cik: '123456'),
      throwsA(isA<FormatException>()),
    );
  });

  test('rejects 13F position dates later than filing/publication',
      () async {
    final payload = envelope();
    (payload['data'] as Map<String, Object?>)['positionDate'] = '2026-09-30';
    (payload['selectedFiling'] as Map<String, Object?>)['reportDate'] =
        '2026-09-30';
    final source = AthenaBackendRelevantInvestorDataSource(
      baseUrl: 'https://api.athena.test',
      client: MockClient((_) async => http.Response(jsonEncode(payload), 200)),
    );
    expect(
      () => source.getLatestInstitutionalHoldings(cik: '123456'),
      throwsA(isA<FormatException>()),
    );
  });


  test('stalled SEC 13F request times out and a later request can recover',
      () async {
    final stalled = Completer<http.Response>();
    var calls = 0;
    final source = AthenaBackendRelevantInvestorDataSource(
      baseUrl: 'https://api.athena.test',
      requestTimeout: const Duration(milliseconds: 30),
      client: MockClient((_) {
        calls++;
        if (calls == 1) return stalled.future;
        return Future.value(http.Response(jsonEncode(envelope()), 200));
      }),
    );
    addTearDown(source.dispose);

    await expectLater(
      source.getLatestInstitutionalHoldings(cik: '123456'),
      throwsA(isA<TimeoutException>()),
    );
    final recovered =
        await source.getLatestInstitutionalHoldings(cik: '123456');
    expect(calls, 2);
    expect(recovered.cik, '123456');
    expect(recovered.recommendationPolicy, 'no_advice');
    expect(recovered.productionEligible, isFalse);
  });
}
