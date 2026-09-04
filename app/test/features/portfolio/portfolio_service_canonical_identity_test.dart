import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/repositories/market_repository.dart';
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

class SingleQuoteMarketRepository implements MarketRepository {
  final MarketQuote quote;

  SingleQuoteMarketRepository(this.quote);

  @override
  Future<MarketQuote> getQuote(String symbol) async => quote;
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

MarketQuote refreshedQuote({
  String exchange = 'NMS',
  String currency = 'USD',
  double price = 435,
}) {
  return MarketQuote(
    symbol: 'MSFT',
    companyName: 'Microsoft Corp.',
    currentPrice: price,
    change: 1,
    changePercentage: 0.2,
    currency: currency,
    exchange: exchange,
    quoteType: 'EQUITY',
    updatedAt: DateTime.utc(2026, 9, 3, 16, 30),
    sourceProvider: 'yahoo',
    retrievedAt: DateTime.utc(2026, 9, 3, 16, 31),
  );
}

Future<PortfolioService> serviceWithVerifiedPosition(
  FakePortfolioRepository repository,
) async {
  final service = PortfolioService(
    repository: repository,
    identityResolver: ({required symbol, exchange}) async => verifiedIdentity(),
  );
  await service.createPortfolio(id: 'p1', name: 'Mi cartera', initialCapital: 0);
  await service.addPosition(draftPosition());
  return service;
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

    await expectLater(service.addPosition(draftPosition()), throwsStateError);
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

    await expectLater(service.addPosition(draftPosition()), throwsStateError);
    expect(repository.stored!.positions, isEmpty);
  });

  test('refresh keeps canonical identity when listing and currency still match', () async {
    final repository = FakePortfolioRepository();
    final service = await serviceWithVerifiedPosition(repository);

    final report = await service.refreshCurrentPrices(
      marketRepository: SingleQuoteMarketRepository(refreshedQuote()),
    );

    expect(report.isComplete, isTrue);
    final stored = repository.stored!.positions.single;
    expect(stored.currentPrice, 435);
    expect(stored.canonicalInstrumentId, 'MSFT@NMS');
    expect(stored.databaseInstrumentId, 42);
    expect(stored.hasVerifiedCanonicalIdentity, isTrue);
  });

  test('refresh rejects listing drift and preserves prior verified position', () async {
    final repository = FakePortfolioRepository();
    final service = await serviceWithVerifiedPosition(repository);
    final before = repository.stored!.positions.single;

    final report = await service.refreshCurrentPrices(
      marketRepository: SingleQuoteMarketRepository(
        refreshedQuote(exchange: 'NYQ', price: 999),
      ),
    );

    expect(report.updatedPositions, 0);
    expect(report.failedSymbols, ['MSFT']);
    final stored = service.portfolio!.positions.single;
    expect(stored.currentPrice, before.currentPrice);
    expect(stored.exchange, 'NMS');
    expect(stored.canonicalInstrumentId, 'MSFT@NMS');
  });

  test('refresh rejects currency drift and preserves prior verified position', () async {
    final repository = FakePortfolioRepository();
    final service = await serviceWithVerifiedPosition(repository);
    final before = repository.stored!.positions.single;

    final report = await service.refreshCurrentPrices(
      marketRepository: SingleQuoteMarketRepository(
        refreshedQuote(currency: 'EUR', price: 999),
      ),
    );

    expect(report.updatedPositions, 0);
    expect(report.failedSymbols, ['MSFT']);
    final stored = service.portfolio!.positions.single;
    expect(stored.currentPrice, before.currentPrice);
    expect(stored.priceCurrency, 'USD');
    expect(stored.canonicalInstrumentId, 'MSFT@NMS');
  });
}
