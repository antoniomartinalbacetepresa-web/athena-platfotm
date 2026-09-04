import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/portfolio/models/portfolio.dart';
import 'package:app/features/portfolio/models/portfolio_instrument_identity.dart';
import 'package:app/features/portfolio/models/portfolio_position.dart';
import 'package:app/features/portfolio/repositories/portfolio_repository.dart';
import 'package:app/features/portfolio/services/portfolio_service.dart';

class FakePortfolioRepository extends PortfolioRepository {
  Portfolio? stored;

  @override
  Future<Portfolio?> loadPortfolio() async => stored;

  @override
  Future<void> savePortfolio(Portfolio portfolio) async {
    stored = portfolio;
  }

  @override
  Future<void> deletePortfolio() async {
    stored = null;
  }
}

PortfolioPosition draftPosition() {
  return PortfolioPosition(
    symbol: 'MSFT',
    companyName: 'Microsoft Corp.',
    shares: 2,
    averagePrice: 400,
    currentPrice: 432.10,
    priceCurrency: 'USD',
    exchange: 'NMS',
    quoteType: 'EQUITY',
    currentPriceUpdatedAt: DateTime.utc(2026, 9, 2, 16, 30),
    currentPriceSourceProvider: 'yahoo',
    currentPriceRetrievedAt: DateTime.utc(2026, 9, 2, 16, 31),
  );
}

PortfolioInstrumentIdentity verifiedIdentity({
  String currency = 'USD',
  bool riskReady = true,
  bool exchangeVerified = true,
}) {
  return PortfolioInstrumentIdentity(
    databaseInstrumentId: 42,
    canonicalInstrumentId: 'MSFT@NMS',
    issuerId: 'issuer:microsoft',
    symbol: 'MSFT',
    exchange: 'NMS',
    exchangeShortName: 'NMS',
    currency: currency,
    sourceProvider: 'yahoo_catalog',
    retrievedAt: DateTime.utc(2026, 9, 2, 16, 32),
    resolutionMethod: 'symbol_and_exchange_exact',
    exchangeVerified: exchangeVerified,
    isRiskReady: riskReady,
    isWeightingReady: false,
    recommendationPolicy: 'no_advice',
    productionEligible: false,
    automaticTrading: false,
  );
}

void main() {
  test('persists only after canonical identity enrichment succeeds', () async {
    final repository = FakePortfolioRepository();
    final service = PortfolioService(
      repository: repository,
      identityResolver: ({required symbol, exchange}) async {
        expect(symbol, 'MSFT');
        expect(exchange, 'NMS');
        return verifiedIdentity();
      },
    );

    await service.createPortfolio(id: 'p1', name: 'Mi cartera', initialCapital: 0);
    await service.addPosition(draftPosition());

    final stored = repository.stored!.positions.single;
    expect(stored.databaseInstrumentId, 42);
    expect(stored.canonicalInstrumentId, 'MSFT@NMS');
    expect(stored.canonicalIssuerId, 'issuer:microsoft');
    expect(stored.identitySourceProvider, 'yahoo_catalog');
    expect(stored.identityRiskReady, isTrue);
    expect(stored.identityExchangeVerified, isTrue);
    expect(stored.hasVerifiedCanonicalIdentity, isTrue);
  });

  test('does not persist when canonical identity is not risk-ready', () async {
    final repository = FakePortfolioRepository();
    final service = PortfolioService(
      repository: repository,
      identityResolver: ({required symbol, exchange}) async =>
          verifiedIdentity(riskReady: false, exchangeVerified: false),
    );

    await service.createPortfolio(id: 'p1', name: 'Mi cartera', initialCapital: 0);

    await expectLater(
      service.addPosition(draftPosition()),
      throwsStateError,
    );
    expect(repository.stored!.positions, isEmpty);
  });

  test('does not persist when canonical identity currency mismatches quote', () async {
    final repository = FakePortfolioRepository();
    final service = PortfolioService(
      repository: repository,
      identityResolver: ({required symbol, exchange}) async =>
          verifiedIdentity(currency: 'EUR'),
    );

    await service.createPortfolio(id: 'p1', name: 'Mi cartera', initialCapital: 0);

    await expectLater(
      service.addPosition(draftPosition()),
      throwsStateError,
    );
    expect(repository.stored!.positions, isEmpty);
  });
}
