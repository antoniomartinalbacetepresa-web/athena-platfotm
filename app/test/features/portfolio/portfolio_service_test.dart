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
        const PortfolioPosition(
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
        const PortfolioPosition(
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
        const PortfolioPosition(
          symbol: 'FAIL',
          companyName: 'Unavailable',
          shares: 1,
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
