import '../../market/models/market_quote.dart';
import '../../market/repositories/market_repository.dart';
import '../models/portfolio.dart';
import '../models/portfolio_position.dart';
import '../repositories/portfolio_repository.dart';

class PortfolioPriceRefreshReport {
  final int totalPositions;
  final int updatedPositions;
  final List<String> failedSymbols;

  const PortfolioPriceRefreshReport({
    required this.totalPositions,
    required this.updatedPositions,
    required this.failedSymbols,
  });

  bool get isComplete =>
      totalPositions == updatedPositions && failedSymbols.isEmpty;

  bool get hasFailures => failedSymbols.isNotEmpty;
}

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

  Future<PortfolioPriceRefreshReport> refreshCurrentPrices({
    required MarketRepository marketRepository,
  }) async {
    final portfolio = _portfolio;
    if (portfolio == null || portfolio.positions.isEmpty) {
      return const PortfolioPriceRefreshReport(
        totalPositions: 0,
        updatedPositions: 0,
        failedSymbols: [],
      );
    }

    final refreshed = <PortfolioPosition>[];
    final failedSymbols = <String>[];
    var updatedCount = 0;

    for (final position in portfolio.positions) {
      try {
        final quote = await marketRepository.getQuote(position.symbol);
        _validateRefreshQuote(quote, expectedSymbol: position.symbol);

        refreshed.add(
          position.copyWith(
            currentPrice: quote.currentPrice,
            currentPriceUpdatedAt: quote.updatedAt,
            currentPriceSourceProvider: quote.sourceProvider!.trim(),
            currentPriceRetrievedAt: quote.retrievedAt,
          ),
        );
        updatedCount += 1;
      } catch (_) {
        refreshed.add(position);
        failedSymbols.add(position.symbol);
      }
    }

    _portfolio = portfolio.copyWith(positions: refreshed);

    if (updatedCount > 0) {
      await _repository.savePortfolio(_portfolio!);
    }

    return PortfolioPriceRefreshReport(
      totalPositions: portfolio.positions.length,
      updatedPositions: updatedCount,
      failedSymbols: List.unmodifiable(failedSymbols),
    );
  }

  void _validateRefreshQuote(
    MarketQuote quote, {
    required String expectedSymbol,
  }) {
    final normalizedExpectedSymbol = expectedSymbol.trim().toUpperCase();
    final normalizedQuoteSymbol = quote.symbol.trim().toUpperCase();
    if (normalizedExpectedSymbol.isEmpty ||
        normalizedQuoteSymbol != normalizedExpectedSymbol) {
      throw StateError('La cotización no corresponde a la posición solicitada.');
    }

    if (!quote.currentPrice.isFinite || quote.currentPrice <= 0) {
      throw StateError('Cotización actual inválida.');
    }

    final sourceProvider = quote.sourceProvider?.trim();
    if (sourceProvider == null || sourceProvider.isEmpty) {
      throw StateError('Cotización sin proveedor de origen verificable.');
    }

    final retrievedAt = quote.retrievedAt;
    if (retrievedAt == null) {
      throw StateError('Cotización sin timestamp de recuperación.');
    }

    if (retrievedAt.isBefore(quote.updatedAt)) {
      throw StateError(
        'La recuperación no puede preceder a la observación de mercado.',
      );
    }
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

  Future<void> addPosition(PortfolioPosition position) async {
    final portfolio = _portfolio;
    if (portfolio == null) {
      throw StateError('No existe una cartera.');
    }

    final verifiedPosition = _validateNewPosition(position);
    final normalizedSymbol = verifiedPosition.symbol;
    final alreadyExists = portfolio.positions.any(
      (existing) => existing.symbol.trim().toUpperCase() == normalizedSymbol,
    );
    if (alreadyExists) {
      throw StateError(
        'Ya existe una posición para $normalizedSymbol. '
        'ATHENA no duplica exposición sin una operación explícita de ajuste.',
      );
    }

    final updatedPositions = [...portfolio.positions, verifiedPosition];

    _portfolio = portfolio.copyWith(positions: updatedPositions);
    await _repository.savePortfolio(_portfolio!);
  }

  PortfolioPosition _validateNewPosition(PortfolioPosition position) {
    final symbol = position.symbol.trim().toUpperCase();
    if (symbol.isEmpty) {
      throw ArgumentError.value(position.symbol, 'symbol', 'Ticker vacío.');
    }

    final companyName = position.companyName.trim();
    if (companyName.isEmpty) {
      throw ArgumentError.value(
        position.companyName,
        'companyName',
        'La identidad visible del instrumento no puede estar vacía.',
      );
    }

    if (!position.shares.isFinite || position.shares <= 0) {
      throw ArgumentError.value(
        position.shares,
        'shares',
        'El número de acciones debe ser finito y mayor que cero.',
      );
    }
    if (!position.averagePrice.isFinite || position.averagePrice <= 0) {
      throw ArgumentError.value(
        position.averagePrice,
        'averagePrice',
        'El precio medio debe ser finito y mayor que cero.',
      );
    }
    if (!position.currentPrice.isFinite || position.currentPrice <= 0) {
      throw ArgumentError.value(
        position.currentPrice,
        'currentPrice',
        'El precio actual debe ser finito y mayor que cero.',
      );
    }

    final updatedAt = position.currentPriceUpdatedAt;
    final sourceProvider = position.currentPriceSourceProvider?.trim();
    final retrievedAt = position.currentPriceRetrievedAt;
    if (updatedAt == null ||
        sourceProvider == null ||
        sourceProvider.isEmpty ||
        retrievedAt == null) {
      throw StateError(
        'Una posición nueva requiere provenance completa de su cotización.',
      );
    }
    if (retrievedAt.isBefore(updatedAt)) {
      throw StateError(
        'La recuperación de la cotización no puede preceder a su observación.',
      );
    }

    return position.copyWith(
      symbol: symbol,
      companyName: companyName,
      currentPriceSourceProvider: sourceProvider,
    );
  }

  Future<void> removePosition(String symbol) async {
    if (_portfolio == null) {
      throw StateError('No existe una cartera.');
    }

    final normalizedSymbol = symbol.trim().toUpperCase();
    final updatedPositions = _portfolio!.positions
        .where(
          (position) =>
              position.symbol.trim().toUpperCase() != normalizedSymbol,
        )
        .toList();

    _portfolio = _portfolio!.copyWith(positions: updatedPositions);
    await _repository.savePortfolio(_portfolio!);
  }

  Future<void> updatePosition(PortfolioPosition updatedPosition) async {
    if (_portfolio == null) {
      throw StateError('No existe una cartera.');
    }

    final updatedPositions = _portfolio!.positions.map((position) {
      if (position.symbol == updatedPosition.symbol) {
        return updatedPosition;
      }
      return position;
    }).toList();

    _portfolio = _portfolio!.copyWith(positions: updatedPositions);
    await _repository.savePortfolio(_portfolio!);
  }

  Future<void> clearPortfolio() async {
    _portfolio = null;
    await _repository.deletePortfolio();
  }
}
