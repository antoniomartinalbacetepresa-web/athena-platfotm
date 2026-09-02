import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/repositories/market_repository.dart';
import 'package:app/features/portfolio/models/portfolio.dart';
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

class FakeMarketRepository implements MarketRepository {
  final Map<String, MarketQuote> quotes;
  final Set<String> failures;

  FakeMarketRepository({
    this.quotes = const {},
    this.failures = const {},
  });

  @override
  Future<MarketQuote> getQuote(String symbol) async {
    if (failures.contains(symbol)) {
      throw StateError('quote unavailable');
    }

    final quote = quotes[symbol];
    if (quote == null) {
      throw StateError('missing quote');
    }
    return quote;
  }
}

PortfolioPosition verifiedPosition({
  required String symbol,
  String? companyName,
  double shares = 1,
  double averagePrice = 100,
  double currentPrice = 101,
}) {
  final observedAt = DateTime.utc(2026, 9, 2, 16, 30);
  return PortfolioPosition(
    symbol: symbol,
    companyName: companyName ?? '$symbol Company',
    shares: shares,
    averagePrice: averagePrice,
    currentPrice: currentPrice,
    currentPriceUpdatedAt: observedAt,
    currentPriceSourceProvider: 'yahoo',
    currentPriceRetrievedAt: observedAt.add(const Duration(seconds: 2)),
  );
}

void main() {
  group('PortfolioService reference capital', () {
    test('creates an empty portfolio when reference capital is set first', () async {
      final repository = FakePortfolioRepository();
      final service = PortfolioService(repository: repository);

      await service.updateReferenceCapital(10000);

      expect(service.portfolio, isNotNull);
      expect(service.portfolio!.initialCapital, 10000);
      expect(service.portfolio!.positions, isEmpty);
      expect(repository.stored!.initialCapital, 10000);
    });

    test('preserves real positions when reference capital changes', () async {
      final repository = FakePortfolioRepository();
      final service = PortfolioService(repository: repository);

      await service.createPortfolio(
        id: 'portfolio-1',
        name: 'Mi cartera',
        initialCapital: 5000,
      );
      await service.addPosition(
        verifiedPosition(
          symbol: 'TEST',
          companyName: 'Test Company',
          shares: 2,
          averagePrice: 100,
          currentPrice: 110,
        ),
      );

      await service.updateReferenceCapital(7500);

      expect(service.portfolio!.initialCapital, 7500);
      expect(service.portfolio!.positions, hasLength(1));
      expect(service.portfolio!.positions.single.symbol, 'TEST');
    });

    test('rejects negative or non-finite reference capital', () async {
      final repository = FakePortfolioRepository();
      final service = PortfolioService(repository: repository);

      expect(
        () => service.updateReferenceCapital(-1),
        throwsArgumentError,
      );
      expect(
        () => service.updateReferenceCapital(double.nan),
        throwsArgumentError,
      );
      expect(
        () => service.updateReferenceCapital(double.infinity),
        throwsArgumentError,
      );
    });
  });

  group('PortfolioService new position integrity', () {
    test('normalizes and persists a fully verified position', () async {
      final repository = FakePortfolioRepository();
      final service = PortfolioService(repository: repository);
      await service.createPortfolio(
        id: 'verified',
        name: 'Mi cartera',
        initialCapital: 5000,
      );

      await service.addPosition(
        verifiedPosition(symbol: ' msft ', companyName: ' Microsoft '),
      );

      final stored = repository.stored!.positions.single;
      expect(stored.symbol, 'MSFT');
      expect(stored.companyName, 'Microsoft');
      expect(stored.currentPriceSourceProvider, 'yahoo');
      expect(stored.currentPriceRetrievedAt, isNotNull);
    });

    test('rejects a new position without complete quote provenance', () async {
      final repository = FakePortfolioRepository();
      final service = PortfolioService(repository: repository);
      await service.createPortfolio(
        id: 'missing-provenance',
        name: 'Mi cartera',
        initialCapital: 5000,
      );

      expect(
        () => service.addPosition(
          const PortfolioPosition(
            symbol: 'AAPL',
            companyName: 'Apple',
            shares: 1,
            averagePrice: 100,
            currentPrice: 110,
          ),
        ),
        throwsStateError,
      );
      expect(service.portfolio!.positions, isEmpty);
    });

    test('rejects invalid finite economics for a new position', () async {
      final repository = FakePortfolioRepository();
      final service = PortfolioService(repository: repository);
      await service.createPortfolio(
        id: 'invalid-economics',
        name: 'Mi cartera',
        initialCapital: 5000,
      );

      expect(
        () => service.addPosition(
          verifiedPosition(symbol: 'ZERO', shares: 0),
        ),
        throwsArgumentError,
      );
      expect(
        () => service.addPosition(
          verifiedPosition(symbol: 'NAN', currentPrice: double.nan),
        ),
        throwsArgumentError,
      );
      expect(service.portfolio!.positions, isEmpty);
    });

    test('rejects duplicate exposure for the same normalized symbol', () async {
      final repository = FakePortfolioRepository();
      final service = PortfolioService(repository: repository);
      await service.createPortfolio(
        id: 'duplicates',
        name: 'Mi cartera',
        initialCapital: 5000,
      );

      await service.addPosition(verifiedPosition(symbol: 'AAPL'));

      expect(
        () => service.addPosition(verifiedPosition(symbol: ' aapl ')),
        throwsStateError,
      );
      expect(service.portfolio!.positions, hasLength(1));
    });

    test('rejects provenance whose retrieval predates observation', () async {
      final repository = FakePortfolioRepository();
      final service = PortfolioService(repository: repository);
      await service.createPortfolio(
        id: 'bad-time',
        name: 'Mi cartera',
        initialCapital: 5000,
      );
      final observedAt = DateTime.utc(2026, 9, 2, 16, 30);

      expect(
        () => service.addPosition(
          PortfolioPosition(
            symbol: 'TIME',
            companyName: 'Temporal integrity',
            shares: 1,
            averagePrice: 100,
            currentPrice: 101,
            currentPriceUpdatedAt: observedAt,
            currentPriceSourceProvider: 'yahoo',
            currentPriceRetrievedAt:
                observedAt.subtract(const Duration(seconds: 1)),
          ),
        ),
        throwsStateError,
      );
      expect(service.portfolio!.positions, isEmpty);
    });
  });

  group('PortfolioService market refresh', () {
    test('refreshes and persists price, timestamp and source provenance', () async {
      final repository = FakePortfolioRepository();
      final service = PortfolioService(repository: repository);
      await service.createPortfolio(
        id: 'p1',
        name: 'Mi cartera',
        initialCapital: 5000,
      );
      await service.addPosition(
        verifiedPosition(
          symbol: 'AAPL',
          companyName: 'Apple',
          shares: 2,
          averagePrice: 100,
          currentPrice: 101,
        ),
      );

      final updatedAt = DateTime.utc(2026, 9, 2, 16, 45);
      final retrievedAt = DateTime.utc(2026, 9, 2, 16, 45, 2);
      final report = await service.refreshCurrentPrices(
        marketRepository: FakeMarketRepository(
          quotes: {
            'AAPL': MarketQuote(
              symbol: 'AAPL',
              companyName: 'AAPL',
              currentPrice: 125,
              change: 1,
              changePercentage: 0.8,
              updatedAt: updatedAt,
              sourceProvider: 'yahoo',
              retrievedAt: retrievedAt,
            ),
          },
        ),
      );

      expect(report.isComplete, isTrue);
      expect(report.updatedPositions, 1);
      expect(report.failedSymbols, isEmpty);

      final position = service.portfolio!.positions.single;
      expect(position.currentPrice, 125);
      expect(position.currentPriceUpdatedAt, updatedAt);
      expect(position.currentPriceSourceProvider, 'yahoo');
      expect(position.currentPriceRetrievedAt, retrievedAt);

      final persisted = repository.stored!.positions.single;
      expect(persisted.currentPrice, 125);
      expect(persisted.currentPriceSourceProvider, 'yahoo');
      expect(persisted.currentPriceRetrievedAt, retrievedAt);
    });

    test('preserves last known price and reports symbols that fail', () async {
      final repository = FakePortfolioRepository();
      final service = PortfolioService(repository: repository);
      await service.createPortfolio(
        id: 'p2',
        name: 'Mi cartera',
        initialCapital: 5000,
      );
      await service.addPosition(
        verifiedPosition(
          symbol: 'FAIL',
          companyName: 'Unavailable',
          averagePrice: 90,
          currentPrice: 95,
        ),
      );

      final report = await service.refreshCurrentPrices(
        marketRepository: FakeMarketRepository(failures: {'FAIL'}),
      );

      expect(report.hasFailures, isTrue);
      expect(report.updatedPositions, 0);
      expect(report.failedSymbols, ['FAIL']);
      expect(service.portfolio!.positions.single.currentPrice, 95);
    });

    test('rejects refreshed prices without source provenance', () async {
      final repository = FakePortfolioRepository();
      final service = PortfolioService(repository: repository);
      await service.createPortfolio(
        id: 'p3',
        name: 'Mi cartera',
        initialCapital: 5000,
      );
      await service.addPosition(
        verifiedPosition(symbol: 'NOPROV', companyName: 'No provenance'),
      );

      final observedAt = DateTime.utc(2026, 9, 2, 16, 45);
      final report = await service.refreshCurrentPrices(
        marketRepository: FakeMarketRepository(
          quotes: {
            'NOPROV': MarketQuote(
              symbol: 'NOPROV',
              companyName: 'No provenance',
              currentPrice: 120,
              change: 1,
              changePercentage: 0.8,
              updatedAt: observedAt,
              sourceProvider: null,
              retrievedAt: observedAt.add(const Duration(seconds: 2)),
            ),
          },
        ),
      );

      expect(report.hasFailures, isTrue);
      expect(report.updatedPositions, 0);
      expect(report.failedSymbols, ['NOPROV']);
      expect(service.portfolio!.positions.single.currentPrice, 101);
    });

    test('rejects retrieval timestamps earlier than market observation', () async {
      final repository = FakePortfolioRepository();
      final service = PortfolioService(repository: repository);
      await service.createPortfolio(
        id: 'p4',
        name: 'Mi cartera',
        initialCapital: 5000,
      );
      await service.addPosition(
        verifiedPosition(symbol: 'TIME', companyName: 'Temporal integrity'),
      );

      final observedAt = DateTime.utc(2026, 9, 2, 16, 45);
      final report = await service.refreshCurrentPrices(
        marketRepository: FakeMarketRepository(
          quotes: {
            'TIME': MarketQuote(
              symbol: 'TIME',
              companyName: 'Temporal integrity',
              currentPrice: 120,
              change: 1,
              changePercentage: 0.8,
              updatedAt: observedAt,
              sourceProvider: 'yahoo',
              retrievedAt: observedAt.subtract(const Duration(seconds: 1)),
            ),
          },
        ),
      );

      expect(report.hasFailures, isTrue);
      expect(report.updatedPositions, 0);
      expect(report.failedSymbols, ['TIME']);
      expect(service.portfolio!.positions.single.currentPrice, 101);
    });

    test('rejects refreshed quote for a different symbol', () async {
      final repository = FakePortfolioRepository();
      final service = PortfolioService(repository: repository);
      await service.createPortfolio(
        id: 'p5',
        name: 'Mi cartera',
        initialCapital: 5000,
      );
      await service.addPosition(verifiedPosition(symbol: 'MSFT'));

      final observedAt = DateTime.utc(2026, 9, 2, 16, 45);
      final report = await service.refreshCurrentPrices(
        marketRepository: FakeMarketRepository(
          quotes: {
            'MSFT': MarketQuote(
              symbol: 'AAPL',
              companyName: 'Wrong instrument',
              currentPrice: 120,
              change: 1,
              changePercentage: 0.8,
              updatedAt: observedAt,
              sourceProvider: 'yahoo',
              retrievedAt: observedAt.add(const Duration(seconds: 1)),
            ),
          },
        ),
      );

      expect(report.hasFailures, isTrue);
      expect(report.updatedPositions, 0);
      expect(report.failedSymbols, ['MSFT']);
      expect(service.portfolio!.positions.single.currentPrice, 101);
    });

    test('loads legacy positions without quote provenance', () {
      final position = PortfolioPosition.fromMap({
        'symbol': 'LEGACY',
        'companyName': 'Legacy',
        'shares': 1,
        'averagePrice': 10,
        'currentPrice': 11,
      });

      expect(position.currentPriceUpdatedAt, isNull);
      expect(position.currentPriceSourceProvider, isNull);
      expect(position.currentPriceRetrievedAt, isNull);
    });

    test('round-trips persisted quote provenance', () {
      final updatedAt = DateTime.utc(2026, 9, 2, 16, 45);
      final retrievedAt = DateTime.utc(2026, 9, 2, 16, 45, 3);

      final original = PortfolioPosition(
        symbol: 'MSFT',
        companyName: 'Microsoft',
        shares: 3,
        averagePrice: 400,
        currentPrice: 420,
        currentPriceUpdatedAt: updatedAt,
        currentPriceSourceProvider: 'yahoo',
        currentPriceRetrievedAt: retrievedAt,
      );

      final restored = PortfolioPosition.fromMap(original.toMap());

      expect(restored.currentPriceUpdatedAt, updatedAt);
      expect(restored.currentPriceSourceProvider, 'yahoo');
      expect(restored.currentPriceRetrievedAt, retrievedAt);
    });
  });
}
