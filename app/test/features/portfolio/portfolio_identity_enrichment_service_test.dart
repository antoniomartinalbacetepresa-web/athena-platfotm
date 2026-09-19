import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/portfolio/models/portfolio_instrument_identity.dart';
import 'package:app/features/portfolio/models/portfolio_position.dart';
import 'package:app/features/portfolio/services/portfolio_identity_enrichment_service.dart';

void main() {
  const service = PortfolioIdentityEnrichmentService();

  PortfolioPosition position({
    String symbol = 'AAPL',
    String? exchange = 'NASDAQ',
    String? currency = 'USD',
  }) {
    return PortfolioPosition(
      symbol: symbol,
      companyName: 'Apple Inc.',
      shares: 1,
      averagePrice: 100,
      currentPrice: 101,
      exchange: exchange,
      priceCurrency: currency,
      currentPriceUpdatedAt: DateTime.utc(2026, 9, 4, 18),
      currentPriceSourceProvider: 'yahoo',
      currentPriceRetrievedAt: DateTime.utc(2026, 9, 4, 18, 0, 2),
    );
  }

  PortfolioInstrumentIdentity identity({
    String symbol = 'AAPL',
    String exchange = 'NASDAQ',
    String currency = 'USD',
    bool exchangeVerified = true,
    bool riskReady = true,
    String recommendationPolicy = 'no_advice',
    bool productionEligible = false,
    bool automaticTrading = false,
  }) {
    return PortfolioInstrumentIdentity(
      databaseInstrumentId: 7,
      canonicalInstrumentId: '$symbol@$exchange',
      issuerId: 'issuer:apple',
      symbol: symbol,
      exchange: exchange,
      exchangeShortName: exchange,
      currency: currency,
      sourceProvider: 'yahoo_catalog',
      retrievedAt: DateTime.utc(2026, 9, 4, 18, 1),
      resolutionMethod: 'symbol_and_exchange_exact',
      exchangeVerified: exchangeVerified,
      isRiskReady: riskReady,
      isWeightingReady: false,
      recommendationPolicy: recommendationPolicy,
      productionEligible: productionEligible,
      automaticTrading: automaticTrading,
    );
  }

  test('enriches a position only with verified canonical identity', () async {
    final enriched = await service.enrich(
      position: position(),
      resolver: ({required symbol, exchange}) async {
        expect(symbol, 'AAPL');
        expect(exchange, 'NASDAQ');
        return identity();
      },
    );

    expect(enriched.databaseInstrumentId, 7);
    expect(enriched.canonicalInstrumentId, 'AAPL@NASDAQ');
    expect(enriched.canonicalIssuerId, 'issuer:apple');
    expect(enriched.identitySourceProvider, 'yahoo_catalog');
    expect(enriched.identityExchangeVerified, isTrue);
    expect(enriched.identityRiskReady, isTrue);
    expect(enriched.hasVerifiedCanonicalIdentity, isTrue);
  });

  test('fails closed when exchange is absent', () async {
    expect(
      () => service.enrich(
        position: position(exchange: null),
        resolver: ({required symbol, exchange}) async => identity(),
      ),
      throwsStateError,
    );
  });

  test('fails closed on symbol, listing or currency mismatch', () async {
    for (final badIdentity in [
      identity(symbol: 'MSFT'),
      identity(exchange: 'NYSE'),
      identity(currency: 'EUR'),
    ]) {
      expect(
        () => service.enrich(
          position: position(),
          resolver: ({required symbol, exchange}) async => badIdentity,
        ),
        throwsStateError,
      );
    }
  });

  test('diagnostic identity cannot become risk-ready', () async {
    expect(
      () => service.enrich(
        position: position(),
        resolver: ({required symbol, exchange}) async =>
            identity(exchangeVerified: false, riskReady: false),
      ),
      throwsStateError,
    );
  });

  test('identity cannot elevate advice, production or trading', () async {
    for (final badIdentity in [
      identity(recommendationPolicy: 'advice'),
      identity(productionEligible: true),
      identity(automaticTrading: true),
    ]) {
      expect(
        () => service.enrich(
          position: position(),
          resolver: ({required symbol, exchange}) async => badIdentity,
        ),
        throwsStateError,
      );
    }
  });
}
