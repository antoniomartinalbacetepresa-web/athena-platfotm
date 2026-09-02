import '../models/portfolio.dart';
import '../models/portfolio_position.dart';
import '../repositories/portfolio_repository.dart';

class PortfolioService {
  PortfolioService({
    PortfolioRepository? repository,
  }) : _repository = repository ?? PortfolioRepository();

  final PortfolioRepository _repository;

  Portfolio? _portfolio;

  Portfolio? get portfolio => _portfolio;

  bool get hasPortfolio => _portfolio != null;

  Future<void> loadPortfolio() async {
    _portfolio = await _repository.loadPortfolio();
  }

  Future<void> createPortfolio({
    required String id,
    required String name,
    required double initialCapital,
  }) async {
    if (!initialCapital.isFinite || initialCapital < 0) {
      throw ArgumentError.value(
        initialCapital,
        'initialCapital',
        'El capital de referencia debe ser finito y no negativo.',
      );
    }

    _portfolio = Portfolio(
      id: id,
      name: name,
      initialCapital: initialCapital,
      positions: const [],
      createdAt: DateTime.now(),
    );

    await _repository.savePortfolio(_portfolio!);
  }

  Future<void> updateReferenceCapital(double referenceCapital) async {
    if (!referenceCapital.isFinite || referenceCapital < 0) {
      throw ArgumentError.value(
        referenceCapital,
        'referenceCapital',
        'El capital de referencia debe ser finito y no negativo.',
      );
    }

    if (_portfolio == null) {
      await createPortfolio(
        id: DateTime.now().millisecondsSinceEpoch.toString(),
        name: 'Mi cartera',
        initialCapital: referenceCapital,
      );
      return;
    }

    _portfolio = _portfolio!.copyWith(initialCapital: referenceCapital);
    await _repository.savePortfolio(_portfolio!);
  }

  Future<void> addPosition(
    PortfolioPosition position,
  ) async {
    if (_portfolio == null) {
      throw StateError('No existe una cartera.');
    }

    final updatedPositions = [
      ..._portfolio!.positions,
      position,
    ];

    _portfolio = _portfolio!.copyWith(
      positions: updatedPositions,
    );

    await _repository.savePortfolio(_portfolio!);
  }

  Future<void> removePosition(
    String symbol,
  ) async {
    if (_portfolio == null) {
      throw StateError('No existe una cartera.');
    }

    final updatedPositions = _portfolio!.positions
        .where(
          (position) => position.symbol != symbol,
        )
        .toList();

    _portfolio = _portfolio!.copyWith(
      positions: updatedPositions,
    );

    await _repository.savePortfolio(_portfolio!);
  }

  Future<void> updatePosition(
    PortfolioPosition updatedPosition,
  ) async {
    if (_portfolio == null) {
      throw StateError('No existe una cartera.');
    }

    final updatedPositions = _portfolio!.positions.map(
      (position) {
        if (position.symbol == updatedPosition.symbol) {
          return updatedPosition;
        }

        return position;
      },
    ).toList();

    _portfolio = _portfolio!.copyWith(
      positions: updatedPositions,
    );

    await _repository.savePortfolio(_portfolio!);
  }

  Future<void> clearPortfolio() async {
    _portfolio = null;

    await _repository.deletePortfolio();
  }
}
