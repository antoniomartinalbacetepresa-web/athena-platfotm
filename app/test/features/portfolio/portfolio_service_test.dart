import 'package:flutter_test/flutter_test.dart';

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
}
