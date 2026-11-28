import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/portfolio/models/portfolio.dart';
import 'package:app/features/portfolio/models/portfolio_position.dart';
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

PortfolioPosition _position({
  String symbol = 'AAPL',
  double shares = 2,
  String? positionSourceProvider,
  DateTime? positionObservedAt,
  DateTime? positionRetrievedAt,
}) {
  final marketObservedAt = DateTime.utc(2026, 9, 5, 8);
  return PortfolioPosition(
    symbol: symbol,
    companyName: 'Apple',
    shares: shares,
    averagePrice: 100,
    currentPrice: 110,
    currentPriceUpdatedAt: marketObservedAt,
    currentPriceSourceProvider: 'yahoo_chart',
    currentPriceRetrievedAt: marketObservedAt.add(const Duration(seconds: 1)),
    positionSourceProvider: positionSourceProvider,
    positionObservedAt: positionObservedAt,
    positionRetrievedAt: positionRetrievedAt,
  );
}

Future<PortfolioService> _service(_FakePortfolioRepository repository) async {
  final service = PortfolioService(repository: repository);
  await service.createPortfolio(
    id: 'portfolio-provenance',
    name: 'Mi cartera',
    initialCapital: 10000,
  );
  return service;
}

void main() {
  test('new user position is stamped with declaration provenance', () async {
    final repository = _FakePortfolioRepository();
    final service = await _service(repository);

    await service.addPosition(_position());

    final stored = repository.stored!.positions.single;
    expect(stored.positionSourceProvider, 'user_portfolio_entry');
    expect(stored.positionObservedAt, isNotNull);
    expect(stored.positionRetrievedAt, isNotNull);
    expect(stored.hasVerifiedPositionProvenance, isTrue);
    expect(
      stored.positionRetrievedAt!.isBefore(stored.positionObservedAt!),
      isFalse,
    );

    final roundTrip = PortfolioPosition.fromMap(stored.toMap());
    expect(roundTrip.positionSourceProvider, stored.positionSourceProvider);
    expect(roundTrip.positionObservedAt, stored.positionObservedAt);
    expect(roundTrip.positionRetrievedAt, stored.positionRetrievedAt);
    expect(roundTrip.hasVerifiedPositionProvenance, isTrue);
  });

  test('pre-existing verifiable declaration provenance is preserved', () async {
    final repository = _FakePortfolioRepository();
    final service = await _service(repository);
    final observedAt = DateTime.utc(2026, 9, 4, 12);
    final retrievedAt = observedAt.add(const Duration(seconds: 3));

    await service.addPosition(
      _position(
        positionSourceProvider: 'verified_broker_import',
        positionObservedAt: observedAt,
        positionRetrievedAt: retrievedAt,
      ),
    );

    final stored = repository.stored!.positions.single;
    expect(stored.positionSourceProvider, 'verified_broker_import');
    expect(stored.positionObservedAt, observedAt);
    expect(stored.positionRetrievedAt, retrievedAt);
  });

  test('explicit position update creates a new declaration attestation', () async {
    final repository = _FakePortfolioRepository();
    final service = await _service(repository);
    await service.addPosition(_position());
    final existing = repository.stored!.positions.single;

    await service.updatePosition(existing.copyWith(shares: 3));

    final updated = repository.stored!.positions.single;
    expect(updated.shares, 3);
    expect(updated.positionSourceProvider, 'user_portfolio_update');
    expect(updated.hasVerifiedPositionProvenance, isTrue);
  });

  test('reversed declaration timestamps are not verified', () {
    final observedAt = DateTime.utc(2026, 9, 5, 10);
    final position = _position(
      positionSourceProvider: 'user_portfolio_entry',
      positionObservedAt: observedAt,
      positionRetrievedAt: observedAt.subtract(const Duration(seconds: 1)),
    );

    expect(position.hasVerifiedPositionProvenance, isFalse);
  });
}
