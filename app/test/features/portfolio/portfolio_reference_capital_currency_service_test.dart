import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/portfolio/models/portfolio.dart';
import 'package:app/features/portfolio/repositories/portfolio_repository.dart';
import 'package:app/features/portfolio/services/portfolio_service.dart';

class _FakePortfolioRepository extends PortfolioRepository {
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
  group('PortfolioService reference capital currency', () {
    test('persists an explicitly supplied ISO currency with the amount', () async {
      final repository = _FakePortfolioRepository();
      final service = PortfolioService(repository: repository);

      await service.updateReferenceCapital(
        10000,
        referenceCapitalCurrency: ' usd ',
      );

      expect(service.portfolio!.initialCapital, 10000);
      expect(service.portfolio!.referenceCapitalCurrency, 'USD');
      expect(repository.stored!.referenceCapitalCurrency, 'USD');
    });

    test('amount-only legacy updates preserve the already persisted currency', () async {
      final repository = _FakePortfolioRepository();
      final service = PortfolioService(repository: repository);

      await service.createPortfolio(
        id: 'usd-portfolio',
        name: 'USD portfolio',
        initialCapital: 5000,
        referenceCapitalCurrency: 'USD',
      );

      await service.updateReferenceCapital(7500);

      expect(service.portfolio!.initialCapital, 7500);
      expect(service.portfolio!.referenceCapitalCurrency, 'USD');
      expect(repository.stored!.referenceCapitalCurrency, 'USD');
    });

    test('rejects malformed reference currency instead of reinterpreting it', () async {
      final repository = _FakePortfolioRepository();
      final service = PortfolioService(repository: repository);

      expect(
        () => service.updateReferenceCapital(
          10000,
          referenceCapitalCurrency: 'US',
        ),
        throwsArgumentError,
      );
      expect(repository.stored, isNull);
    });

    test('createPortfolio normalizes explicit currency and rejects invalid values', () async {
      final repository = _FakePortfolioRepository();
      final service = PortfolioService(repository: repository);

      await service.createPortfolio(
        id: 'gbp-portfolio',
        name: 'GBP portfolio',
        initialCapital: 2000,
        referenceCapitalCurrency: 'gbp',
      );
      expect(service.portfolio!.referenceCapitalCurrency, 'GBP');

      expect(
        () => service.createPortfolio(
          id: 'invalid',
          name: 'Invalid',
          initialCapital: 2000,
          referenceCapitalCurrency: 'EURO',
        ),
        throwsArgumentError,
      );
    });
  });
}
