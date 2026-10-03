import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/portfolio/data/athena_backend_portfolio_valuation_data_source.dart';
import 'package:app/features/portfolio/models/portfolio_position.dart';

const valuationFingerprint =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const recordFingerprint =
    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';

PortfolioPosition verifiedPosition({
  bool withProvenance = true,
  bool withIdentity = true,
}) {
  final positionObservedAt = DateTime.utc(2026, 9, 5, 8, 30);
  final priceObservedAt = DateTime.utc(2026, 9, 5, 8);
  return PortfolioPosition(
    symbol: 'AAPL',
    companyName: 'Apple',
    shares: 5,
    averagePrice: 100,
    currentPrice: 110,
    priceCurrency: 'USD',
    exchange: 'NASDAQ',
    currentPriceUpdatedAt: priceObservedAt,
    currentPriceSourceProvider: 'yahoo_chart',
    currentPriceRetrievedAt: priceObservedAt.add(const Duration(seconds: 1)),
    positionSourceProvider: withProvenance ? 'user_portfolio_entry' : null,
    positionObservedAt: withProvenance ? positionObservedAt : null,
    positionRetrievedAt: withProvenance
        ? positionObservedAt.add(const Duration(seconds: 1))
        : null,
    databaseInstrumentId: withIdentity ? 7 : null,
    canonicalInstrumentId: withIdentity ? 'AAPL@NASDAQ' : null,
    canonicalIssuerId: withIdentity ? 'issuer:apple' : null,
    identitySourceProvider: withIdentity ? 'yahoo_catalog' : null,
    identityRetrievedAt:
        withIdentity ? DateTime.utc(2026, 9, 4, 18) : null,
    identityResolutionMethod:
        withIdentity ? 'symbol_and_exchange_exact' : null,
    identityExchangeVerified: withIdentity,
    identityRiskReady: withIdentity,
  );
}

Map<String, Object?> responseData({
  bool productionEligible = false,
  String asOf = '2026-09-05T09:00:00.000Z',
  int instrumentId = 7,
}) {
  return {
    'data': {
      'status': 'portfolio_valuation_evidence_verified_non_advisory',
      'artifactVersion': 'athena-portfolio-valuation-evidence-v1',
      'asOf': asOf,
      'baseCurrency': 'EUR',
      'valuationScope':
          'invested_long_positions_only_cash_liabilities_unsettled_excluded',
      'cashIncluded': false,
      'liabilitiesIncluded': false,
      'positionCount': 1,
      'positions': [
        {
          'instrumentId': instrumentId,
          'positionValueInBaseCurrency': 500.0,
        },
      ],
      'investedPositionsValueInBaseCurrency': 500.0,
      'portfolioValuationEvidenceFingerprint': valuationFingerprint,
      'portfolioValuationEvidenceReady': true,
      'advisoryStatus': 'no_advice',
      'productionEligible': productionEligible,
      'automaticTrading': false,
    },
    'persistence': {
      'sealed': true,
      'persistedAt': '2026-09-05T09:00:01Z',
      'recordFingerprint': recordFingerprint,
    },
  };
}

void main() {
  group('AthenaBackendPortfolioValuationDataSource', () {
    test('envía sólo inputs PIT declarados y acepta evidencia sellada', () async {
      final client = MockClient((request) async {
        expect(request.method, 'POST');
        expect(request.url.path, '/api/v1/portfolio/valuation-evidence');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['baseCurrency'], 'EUR');
        expect(body['asOf'], '2026-09-05T09:00:00.000Z');
        final positions = body['positions'] as List<dynamic>;
        expect(positions, hasLength(1));
        final position = positions.single as Map<String, dynamic>;
        expect(position['instrumentId'], 7);
        expect(position['quantity'], 5.0);
        expect(position['positionSourceProvider'], 'user_portfolio_entry');
        expect(position['marketSourceProvider'], 'yahoo_chart');
        expect(position.containsKey('currentPrice'), isFalse);
        expect(position.containsKey('currentPortfolioValue'), isFalse);
        return http.Response(jsonEncode(responseData()), 200);
      });
      final dataSource = AthenaBackendPortfolioValuationDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final evidence = await dataSource.buildAndSeal(
        positions: [verifiedPosition()],
        baseCurrency: 'eur',
        asOf: DateTime.utc(2026, 9, 5, 9),
      );

      expect(evidence.baseCurrency, 'EUR');
      expect(evidence.positionCount, 1);
      expect(evidence.investedPositionsValueInBaseCurrency, 500);
      expect(evidence.valuationFingerprint, valuationFingerprint);
      expect(evidence.recordFingerprint, recordFingerprint);
    });

    test('bloquea antes de HTTP si falta identidad o provenance', () async {
      var calls = 0;
      final dataSource = AthenaBackendPortfolioValuationDataSource(
        baseUrl: 'https://api.athena.test',
        client: MockClient((request) async {
          calls += 1;
          return http.Response('{}', 200);
        }),
      );

      await expectLater(
        dataSource.buildAndSeal(
          positions: [verifiedPosition(withIdentity: false)],
          baseCurrency: 'EUR',
          asOf: DateTime.utc(2026, 9, 5, 9),
        ),
        throwsStateError,
      );
      await expectLater(
        dataSource.buildAndSeal(
          positions: [verifiedPosition(withProvenance: false)],
          baseCurrency: 'EUR',
          asOf: DateTime.utc(2026, 9, 5, 9),
        ),
        throwsStateError,
      );
      expect(calls, 0);
    });

    test('rechaza un artefacto que intente escapar a producción', () async {
      final dataSource = AthenaBackendPortfolioValuationDataSource(
        baseUrl: 'https://api.athena.test',
        client: MockClient((request) async => http.Response(
              jsonEncode(responseData(productionEligible: true)),
              200,
            )),
      );

      await expectLater(
        dataSource.buildAndSeal(
          positions: [verifiedPosition()],
          baseCurrency: 'EUR',
          asOf: DateTime.utc(2026, 9, 5, 9),
        ),
        throwsA(isA<FormatException>()),
      );
    });

    test('rechaza evidencia de otro corte PIT o instrumento', () async {
      for (final payload in [
        responseData(asOf: '2026-09-05T09:00:01Z'),
        responseData(instrumentId: 8),
      ]) {
        final dataSource = AthenaBackendPortfolioValuationDataSource(
          baseUrl: 'https://api.athena.test',
          client: MockClient((request) async => http.Response(
                jsonEncode(payload),
                200,
              )),
        );

        await expectLater(
          dataSource.buildAndSeal(
            positions: [verifiedPosition()],
            baseCurrency: 'EUR',
            asOf: DateTime.utc(2026, 9, 5, 9),
          ),
          throwsA(isA<FormatException>()),
        );
      }
    });

    test('bloquea una declaración conocida después de asOf', () async {
      final future = verifiedPosition().copyWith(
        positionObservedAt: DateTime.utc(2026, 9, 5, 10),
        positionRetrievedAt: DateTime.utc(2026, 9, 5, 10),
      );
      final dataSource = AthenaBackendPortfolioValuationDataSource(
        baseUrl: 'https://api.athena.test',
        client: MockClient((request) async => http.Response('{}', 200)),
      );

      await expectLater(
        dataSource.buildAndSeal(
          positions: [future],
          baseCurrency: 'EUR',
          asOf: DateTime.utc(2026, 9, 5, 9),
        ),
        throwsStateError,
      );
    });
  });
}
