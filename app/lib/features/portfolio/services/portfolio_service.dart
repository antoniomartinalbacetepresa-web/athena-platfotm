import '../../market/models/market_quote.dart';
import '../../market/repositories/market_repository.dart';
import '../data/athena_backend_portfolio_identity_data_source.dart';
import '../models/portfolio.dart';
import '../models/portfolio_instrument_identity.dart';
import '../models/portfolio_position.dart';
import '../repositories/portfolio_repository.dart';
import 'portfolio_identity_enrichment_service.dart';

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
  static const String _defaultBackendUrl = String.fromEnvironment(
    'ATHENA_BACKEND_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );
  static const PortfolioIdentityEnrichmentService _identityEnrichmentService =
      PortfolioIdentityEnrichmentService();

  PortfolioService({
    PortfolioRepository? repository,
    PortfolioIdentityResolver? identityResolver,
  })  : _repository = repository ?? PortfolioRepository(),
        _identityResolver = identityResolver,
        _requireCanonicalIdentity =
            identityResolver != null || repository == null;

  final PortfolioRepository _repository;
  final PortfolioIdentityResolver? _identityResolver;
  final bool _requireCanonicalIdentity;

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
        _validateRefreshQuote(quote, position: position);

        refreshed.add(
          position.copyWith(
            currentPrice: quote.currentPrice,
            priceCurrency: _normalizedOptional(quote.currency),
            exchange: _normalizedOptional(quote.exchange),
            quoteType: _normalizedOptional(quote.quoteType),
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
    required PortfolioPosition position,
  }) {
    final normalizedExpectedSymbol = position.symbol.trim().toUpperCase();
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

    if (position.hasVerifiedCanonicalIdentity) {
      final persistedExchange = position.exchange?.trim().toUpperCase();
      final refreshedExchange = quote.exchange?.trim().toUpperCase();
      if (persistedExchange == null ||
          persistedExchange.isEmpty ||
          refreshedExchange == null ||
          refreshedExchange.isEmpty ||
          refreshedExchange != persistedExchange) {
        throw StateError(
          'La cotización actual pertenece a un listing distinto de la identidad canónica persistida.',
        );
      }

      final persistedCurrency = position.priceCurrency?.trim().toUpperCase();
      final refreshedCurrency = quote.currency?.trim().toUpperCase();
      if (persistedCurrency == null ||
          !RegExp(r'^[A-Z]{3}$').hasMatch(persistedCurrency) ||
          refreshedCurrency == null ||
          refreshedCurrency != persistedCurrency) {
        throw StateError(
          'La moneda de la cotización actual no coincide con la identidad canónica persistida.',
        );
      }
    }
  }

  String? _normalizedOptional(String? value) {
    final normalized = value?.trim();
    if (normalized == null || normalized.isEmpty) {
      return null;
    }
    return normalized;
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

    final identityEnriched = await _enrichCanonicalIdentity(position);
    final provenanceReady = _withPositionDeclarationProvenance(
      identityEnriched,
      sourceProvider: 'user_portfolio_entry',
    );
    final verifiedPosition = _validateNewPosition(provenanceReady);
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

  PortfolioPosition _withPositionDeclarationProvenance(
    PortfolioPosition position, {
    required String sourceProvider,
    bool forceRefresh = false,
  }) {
    if (!forceRefresh && position.hasVerifiedPositionProvenance) {
      return position;
    }
    final observedAt = DateTime.now().toUtc();
    return position.copyWith(
      positionSourceProvider: sourceProvider,
      positionObservedAt: observedAt,
      positionRetrievedAt: observedAt,
    );
  }

  Future<PortfolioPosition> _enrichCanonicalIdentity(
    PortfolioPosition position,
  ) async {
    if (position.hasVerifiedCanonicalIdentity) {
      return position;
    }
    if (!_requireCanonicalIdentity) {
      return position;
    }

    final resolver = _identityResolver ?? _resolveCanonicalIdentity;
    final enriched = await _identityEnrichmentService.enrich(
      position: position,
      resolver: resolver,
    );
    if (!enriched.hasVerifiedCanonicalIdentity) {
      throw StateError(
        'La posición no puede persistirse sin identidad canónica verificable.',
      );
    }
    return enriched;
  }

  Future<PortfolioInstrumentIdentity> _resolveCanonicalIdentity({
    required String symbol,
    String? exchange,
  }) async {
    final dataSource = AthenaBackendPortfolioIdentityDataSource(
      baseUrl: _defaultBackendUrl,
    );
    try {
      return await dataSource.resolve(symbol: symbol, exchange: exchange);
    } finally {
      dataSource.dispose();
    }
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

    final positionProvider = position.positionSourceProvider?.trim();
    final positionObservedAt = position.positionObservedAt;
    final positionRetrievedAt = position.positionRetrievedAt;
    if (positionProvider == null ||
        positionProvider.isEmpty ||
        positionObservedAt == null ||
        positionRetrievedAt == null) {
      throw StateError(
        'Una posición nueva requiere provenance de la declaración de cartera.',
      );
    }
    if (positionRetrievedAt.isBefore(positionObservedAt)) {
      throw StateError(
        'La recuperación de la declaración no puede preceder a su observación.',
      );
    }
    if (_requireCanonicalIdentity && !position.hasVerifiedCanonicalIdentity) {
      throw StateError(
        'Una posición productiva requiere identidad canónica verificable.',
      );
    }

    return position.copyWith(
      symbol: symbol,
      companyName: companyName,
      currentPriceSourceProvider: sourceProvider,
      positionSourceProvider: positionProvider,
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
    final portfolio = _portfolio;
    if (portfolio == null) {
      throw StateError('No existe una cartera.');
    }

    final normalizedSymbol = updatedPosition.symbol.trim().toUpperCase();
    final index = portfolio.positions.indexWhere(
      (position) => position.symbol.trim().toUpperCase() == normalizedSymbol,
    );
    if (index < 0) {
      throw StateError('La posición que se intenta actualizar no existe.');
    }

    final existing = portfolio.positions[index];
    final existingExchange = existing.exchange?.trim().toUpperCase();
    final requestedExchange = updatedPosition.exchange?.trim().toUpperCase();
    final existingCurrency = existing.priceCurrency?.trim().toUpperCase();
    final requestedCurrency =
        updatedPosition.priceCurrency?.trim().toUpperCase();

    if (existingExchange != requestedExchange ||
        existingCurrency != requestedCurrency) {
      throw StateError(
        'No se puede cambiar listing ni moneda mediante una actualización de posición.',
      );
    }

    if (existing.hasVerifiedCanonicalIdentity) {
      if (updatedPosition.databaseInstrumentId != existing.databaseInstrumentId ||
          updatedPosition.canonicalInstrumentId !=
              existing.canonicalInstrumentId ||
          updatedPosition.canonicalIssuerId != existing.canonicalIssuerId ||
          updatedPosition.identitySourceProvider !=
              existing.identitySourceProvider ||
          updatedPosition.identityRetrievedAt != existing.identityRetrievedAt ||
          updatedPosition.identityResolutionMethod !=
              existing.identityResolutionMethod ||
          updatedPosition.identityExchangeVerified !=
              existing.identityExchangeVerified ||
          updatedPosition.identityRiskReady != existing.identityRiskReady) {
        throw StateError(
          'La identidad canónica de una posición es inmutable durante un ajuste.',
        );
      }
    }

    final candidate = existing.copyWith(
      companyName: updatedPosition.companyName,
      shares: updatedPosition.shares,
      averagePrice: updatedPosition.averagePrice,
      currentPrice: updatedPosition.currentPrice,
      costBasisDate: updatedPosition.costBasisDate,
      currentPriceUpdatedAt: updatedPosition.currentPriceUpdatedAt,
      currentPriceSourceProvider: updatedPosition.currentPriceSourceProvider,
      currentPriceRetrievedAt: updatedPosition.currentPriceRetrievedAt,
    );
    final provenanceReady = _withPositionDeclarationProvenance(
      candidate,
      sourceProvider: 'user_portfolio_update',
      forceRefresh: true,
    );
    final validated = _validateNewPosition(provenanceReady);

    final updatedPositions = [...portfolio.positions];
    updatedPositions[index] = validated;
    _portfolio = portfolio.copyWith(positions: updatedPositions);
    await _repository.savePortfolio(_portfolio!);
  }

  Future<void> clearPortfolio() async {
    _portfolio = null;
    await _repository.deletePortfolio();
  }
}
