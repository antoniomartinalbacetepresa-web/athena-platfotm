import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/portfolio/data/athena_backend_portfolio_identity_data_source.dart';

void main() {
  group('AthenaBackendPortfolioIdentityDataSource', () {
    Map<String, Object?> readyPayload({
      String symbol = 'AAPL',
      String exchange = 'NASDAQ',
      bool riskReady = true,
      bool exchangeVerified = true,
      String recommendationPolicy = 'no_advice',
      bool productionEligible = false,
      bool automaticTrading = false,
    }) {
      return {
        'databaseInstrumentId': 7,
        'canonicalInstrumentId': '$symbol@$exchange',
        'issuerId': 'issuer:apple',
        'symbol': symbol,
        'exchange': exchange,
        'exchangeShortName': exchange,
        'currency': 'USD',
        'sourceProvider': 'yahoo_catalog',
        'retrievedAt': '2026-09-04T18:00:00Z',
        'resolutionMethod': riskReady
            ? 'symbol_and_exchange_exact'
            : 'unique_active_symbol',
        'exchangeVerified': exchangeVerified,
        'isRiskReady': riskReady,
        'isWeightingReady': false,
        'recommendationPolicy': recommendationPolicy,
        'productionEligible': productionEligible,
        'automaticTrading': automaticTrading,
      };
    }

    test('resuelve identidad canónica verificable por símbolo y exchange', () async {
      final client = MockClient((request) async {
        expect(request.url.path, '/api/v1/portfolio/instrument-identity');
        expect(request.url.queryParameters['symbol'], 'AAPL');
        expect(request.url.queryParameters['exchange'], 'NASDAQ');
        return http.Response(jsonEncode({'data': readyPayload()}), 200);
      });
      final dataSource = AthenaBackendPortfolioIdentityDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final identity = await dataSource.resolve(
        symbol: ' aapl ',
        exchange: 'nasdaq',
      );

      expect(identity.databaseInstrumentId, 7);
      expect(identity.canonicalInstrumentId, 'AAPL@NASDAQ');
      expect(identity.currency, 'USD');
      expect(identity.isRiskReady, isTrue);
      expect(identity.recommendationPolicy, 'no_advice');
      expect(identity.productionEligible, isFalse);
      expect(identity.automaticTrading, isFalse);
    });

    test('mantiene resolución diagnóstica como no apta para riesgo', () async {
      final client = MockClient((request) async => http.Response(
            jsonEncode({
              'data': readyPayload(
                riskReady: false,
                exchangeVerified: false,
              ),
            }),
            200,
          ));
      final dataSource = AthenaBackendPortfolioIdentityDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      final identity = await dataSource.resolve(symbol: 'AAPL');

      expect(identity.isRiskReady, isFalse);
      expect(identity.exchangeVerified, isFalse);
      expect(identity.productionEligible, isFalse);
    });

    test('rechaza identidad apta para riesgo con exchange distinto', () async {
      final client = MockClient((request) async => http.Response(
            jsonEncode({'data': readyPayload(exchange: 'NYSE')}),
            200,
          ));
      final dataSource = AthenaBackendPortfolioIdentityDataSource(
        baseUrl: 'https://api.athena.test',
        client: client,
      );

      expect(
        () => dataSource.resolve(symbol: 'AAPL', exchange: 'NASDAQ'),
        throwsA(isA<FormatException>()),
      );
    });

    test('rechaza contrato que intente activar advice o trading', () async {
      for (final payload in [
        readyPayload(recommendationPolicy: 'advice'),
        readyPayload(productionEligible: true),
        readyPayload(automaticTrading: true),
      ]) {
        final dataSource = AthenaBackendPortfolioIdentityDataSource(
          baseUrl: 'https://api.athena.test',
          client: MockClient((request) async => http.Response(
                jsonEncode({'data': payload}),
                200,
              )),
        );

        expect(
          () => dataSource.resolve(symbol: 'AAPL', exchange: 'NASDAQ'),
          throwsA(isA<FormatException>()),
        );
      }
    });

    test('rechaza identidad risk-ready sin exchange verificado', () async {
      final dataSource = AthenaBackendPortfolioIdentityDataSource(
        baseUrl: 'https://api.athena.test',
        client: MockClient((request) async => http.Response(
              jsonEncode({
                'data': readyPayload(exchangeVerified: false),
              }),
              200,
            )),
      );

      expect(
        () => dataSource.resolve(symbol: 'AAPL', exchange: 'NASDAQ'),
        throwsA(isA<FormatException>()),
      );
    });
  });
}
