import '../../market/models/fx_quote.dart';
import '../models/portfolio_position.dart';

typedef CurrentFxRateLoader = Future<FxQuote> Function({
  required String baseCurrency,
  required String quoteCurrency,
});

typedef HistoricalFxRateLoader = Future<FxQuote> Function({
  required String baseCurrency,
  required String quoteCurrency,
  required DateTime observedOn,
});

class PortfolioCurrentValuation {
  final String baseCurrency;
  final double currentValueInBaseCurrency;
  final int positionsValued;
  final List<FxQuote> fxEvidence;
  final List<FxQuote> historicalFxEvidence;
  final double? historicalCostBasisInBaseCurrency;
  final DateTime? latestMarketObservedAt;
  final DateTime? latestMarketRetrievedAt;
  final DateTime? latestFxObservedAt;
  final DateTime? latestFxRetrievedAt;

  const PortfolioCurrentValuation({
    required this.baseCurrency,
    required this.currentValueInBaseCurrency,
    required this.positionsValued,
    required this.fxEvidence,
    this.historicalFxEvidence = const [],
    required this.historicalCostBasisInBaseCurrency,
    required this.latestMarketObservedAt,
    required this.latestMarketRetrievedAt,
    required this.latestFxObservedAt,
    required this.latestFxRetrievedAt,
  });

  bool get hasHistoricalCostBasis =>
      historicalCostBasisInBaseCurrency != null;

  bool get usesFx => fxEvidence.isNotEmpty || historicalFxEvidence.isNotEmpty;

  double? get profitLossInBaseCurrency {
    final costBasis = historicalCostBasisInBaseCurrency;
    if (costBasis == null) {
      return null;
    }
    return currentValueInBaseCurrency - costBasis;
  }

  double? get profitLossPercentage {
    final costBasis = historicalCostBasisInBaseCurrency;
    final profitLoss = profitLossInBaseCurrency;
    if (costBasis == null || profitLoss == null || costBasis <= 0) {
      return null;
    }
    return (profitLoss / costBasis) * 100;
  }
}

/// Values current market value and, when evidence is available, historical
/// cost basis in one base currency.
///
/// Cross-currency cost basis is converted only when the position explicitly
/// persists a [PortfolioPosition.costBasisDate] and the ATHENA backend returns
/// a verifiable historical FX observation for that date. Legacy positions
/// without that economic date remain loadable, but cost basis and P/L stay
/// unavailable rather than being estimated.
class PortfolioCurrentValuationService {
  final CurrentFxRateLoader loadCurrentFxRate;
  final HistoricalFxRateLoader? loadHistoricalFxRate;

  const PortfolioCurrentValuationService({
    required this.loadCurrentFxRate,
    this.loadHistoricalFxRate,
  });

  Future<PortfolioCurrentValuation> value({
    required List<PortfolioPosition> positions,
    String baseCurrency = 'EUR',
  }) async {
    final base = _normalizeCurrency(baseCurrency, 'baseCurrency');
    final currentFxBySourceCurrency = <String, FxQuote>{};
    final historicalFxByKey = <String, FxQuote>{};
    final currentFxEvidence = <FxQuote>[];
    final historicalFxEvidence = <FxQuote>[];

    var currentValueInBase = 0.0;
    var historicalCostBasisInBase = 0.0;
    var historicalCostBasisReady = true;
    DateTime? latestMarketObservedAt;
    DateTime? latestMarketRetrievedAt;

    for (final position in positions) {
      _validatePositionEconomics(position);
      _validateMarketEvidence(position);

      latestMarketObservedAt = _latest(
        latestMarketObservedAt,
        position.currentPriceUpdatedAt!,
      );
      latestMarketRetrievedAt = _latest(
        latestMarketRetrievedAt,
        position.currentPriceRetrievedAt!,
      );

      final sourceCurrency = _normalizeCurrency(
        position.priceCurrency ?? '',
        'priceCurrency(${position.symbol})',
      );

      if (sourceCurrency == base) {
        currentValueInBase += position.currentValue;
        historicalCostBasisInBase += position.investedValue;
        continue;
      }

      var currentFx = currentFxBySourceCurrency[sourceCurrency];
      if (currentFx == null) {
        currentFx = await loadCurrentFxRate(
          baseCurrency: sourceCurrency,
          quoteCurrency: base,
        );
        _validateFxEvidence(
          currentFx,
          expectedBase: sourceCurrency,
          expectedQuote: base,
        );
        currentFxBySourceCurrency[sourceCurrency] = currentFx;
        currentFxEvidence.add(currentFx);
      }

      final convertedCurrent = currentFx.convertCurrent(position.currentValue);
      if (!convertedCurrent.isFinite || convertedCurrent < 0) {
        throw StateError(
          'La conversión FX produjo un valor actual inválido para '
          '${position.symbol}.',
        );
      }
      currentValueInBase += convertedCurrent;

      final costBasisDate = position.costBasisDate;
      final historicalLoader = loadHistoricalFxRate;
      if (costBasisDate == null || historicalLoader == null) {
        historicalCostBasisReady = false;
        continue;
      }

      final normalizedCostDate = costBasisDate.toUtc();
      if (normalizedCostDate.isAfter(position.currentPriceRetrievedAt!.toUtc())) {
        throw StateError(
          'La fecha económica del coste de ${position.symbol} es posterior a la evidencia actual.',
        );
      }

      final historicalKey =
          '$sourceCurrency|${_dateKey(normalizedCostDate)}';
      var historicalFx = historicalFxByKey[historicalKey];
      if (historicalFx == null) {
        try {
          historicalFx = await historicalLoader(
            baseCurrency: sourceCurrency,
            quoteCurrency: base,
            observedOn: normalizedCostDate,
          );
          _validateHistoricalFxEvidence(
            historicalFx,
            expectedBase: sourceCurrency,
            expectedQuote: base,
            expectedDate: normalizedCostDate,
          );
        } catch (_) {
          historicalCostBasisReady = false;
          continue;
        }
        historicalFxByKey[historicalKey] = historicalFx;
        historicalFxEvidence.add(historicalFx);
      }

      final convertedCost = historicalFx.convertCurrent(position.investedValue);
      if (!convertedCost.isFinite || convertedCost < 0) {
        historicalCostBasisReady = false;
        continue;
      }
      historicalCostBasisInBase += convertedCost;
    }

    if (!currentValueInBase.isFinite || currentValueInBase < 0) {
      throw StateError('El valor agregado de cartera no es finito o es negativo.');
    }

    DateTime? latestFxObservedAt;
    DateTime? latestFxRetrievedAt;
    for (final fx in [...currentFxEvidence, ...historicalFxEvidence]) {
      latestFxObservedAt = _latest(latestFxObservedAt, fx.observedAt);
      latestFxRetrievedAt = _latest(latestFxRetrievedAt, fx.retrievedAt);
    }

    return PortfolioCurrentValuation(
      baseCurrency: base,
      currentValueInBaseCurrency: currentValueInBase,
      positionsValued: positions.length,
      fxEvidence: List.unmodifiable(currentFxEvidence),
      historicalFxEvidence: List.unmodifiable(historicalFxEvidence),
      historicalCostBasisInBaseCurrency:
          historicalCostBasisReady ? historicalCostBasisInBase : null,
      latestMarketObservedAt: latestMarketObservedAt,
      latestMarketRetrievedAt: latestMarketRetrievedAt,
      latestFxObservedAt: latestFxObservedAt,
      latestFxRetrievedAt: latestFxRetrievedAt,
    );
  }

  void _validatePositionEconomics(PortfolioPosition position) {
    if (position.symbol.trim().isEmpty) {
      throw StateError('La posición no declara un símbolo verificable.');
    }
    if (!position.shares.isFinite || position.shares <= 0) {
      throw StateError('Cantidad inválida para ${position.symbol}.');
    }
    if (!position.currentPrice.isFinite || position.currentPrice <= 0) {
      throw StateError('Precio actual inválido para ${position.symbol}.');
    }
    if (!position.averagePrice.isFinite || position.averagePrice <= 0) {
      throw StateError('Precio medio inválido para ${position.symbol}.');
    }
    if (!position.currentValue.isFinite || position.currentValue < 0) {
      throw StateError('Valor actual inválido para ${position.symbol}.');
    }
    if (!position.investedValue.isFinite || position.investedValue < 0) {
      throw StateError('Coste histórico inválido para ${position.symbol}.');
    }
  }

  void _validateMarketEvidence(PortfolioPosition position) {
    final provider = position.currentPriceSourceProvider?.trim();
    final observedAt = position.currentPriceUpdatedAt;
    final retrievedAt = position.currentPriceRetrievedAt;

    if (provider == null || provider.isEmpty) {
      throw StateError(
        'La posición ${position.symbol} no declara proveedor del precio actual.',
      );
    }
    if (observedAt == null || retrievedAt == null) {
      throw StateError(
        'La posición ${position.symbol} no conserva timestamps de provenance.',
      );
    }
    if (retrievedAt.isBefore(observedAt)) {
      throw StateError(
        'La recuperación del precio de ${position.symbol} precede a su observación.',
      );
    }
  }

  void _validateFxEvidence(
    FxQuote fx, {
    required String expectedBase,
    required String expectedQuote,
  }) {
    _validateFxCore(
      fx,
      expectedBase: expectedBase,
      expectedQuote: expectedQuote,
    );
    if (fx.historicalPointInTimeEligible) {
      throw StateError(
        'Una cotización FX actual no puede utilizarse como evidencia PIT histórica.',
      );
    }
  }

  void _validateHistoricalFxEvidence(
    FxQuote fx, {
    required String expectedBase,
    required String expectedQuote,
    required DateTime expectedDate,
  }) {
    _validateFxCore(
      fx,
      expectedBase: expectedBase,
      expectedQuote: expectedQuote,
    );
    final observed = fx.observedAt.toUtc();
    final expected = expectedDate.toUtc();
    if (observed.year != expected.year ||
        observed.month != expected.month ||
        observed.day != expected.day) {
      throw StateError(
        'La evidencia FX histórica no corresponde a la fecha económica del coste.',
      );
    }
  }

  void _validateFxCore(
    FxQuote fx, {
    required String expectedBase,
    required String expectedQuote,
  }) {
    if (fx.baseCurrency != expectedBase || fx.quoteCurrency != expectedQuote) {
      throw StateError('La evidencia FX no corresponde al par solicitado.');
    }
    if (!fx.rate.isFinite || fx.rate <= 0) {
      throw StateError('La evidencia FX contiene una tasa inválida.');
    }
    if (fx.sourceProvider.trim().isEmpty) {
      throw StateError('La evidencia FX no declara proveedor.');
    }
    if (fx.sourceSymbol == null || fx.sourceSymbol!.trim().isEmpty) {
      throw StateError('La evidencia FX no declara símbolo fuente.');
    }
    if (fx.retrievedAt.isBefore(fx.observedAt)) {
      throw StateError('La recuperación FX precede a su observación.');
    }
  }

  String _normalizeCurrency(String value, String field) {
    final normalized = value.trim().toUpperCase();
    if (!RegExp(r'^[A-Z]{3}$').hasMatch(normalized)) {
      throw StateError('$field no contiene una moneda ISO verificable.');
    }
    return normalized;
  }

  String _dateKey(DateTime value) {
    final utc = value.toUtc();
    return '${utc.year.toString().padLeft(4, '0')}-'
        '${utc.month.toString().padLeft(2, '0')}-'
        '${utc.day.toString().padLeft(2, '0')}';
  }

  DateTime _latest(DateTime? current, DateTime candidate) {
    if (current == null || candidate.isAfter(current)) {
      return candidate;
    }
    return current;
  }
}
