import '../../market/models/fx_quote.dart';
import '../models/portfolio_position.dart';

typedef CurrentFxRateLoader = Future<FxQuote> Function({
  required String baseCurrency,
  required String quoteCurrency,
});

class PortfolioCurrentValuation {
  final String baseCurrency;
  final double currentValueInBaseCurrency;
  final int positionsValued;
  final List<FxQuote> fxEvidence;
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
    required this.historicalCostBasisInBaseCurrency,
    required this.latestMarketObservedAt,
    required this.latestMarketRetrievedAt,
    required this.latestFxObservedAt,
    required this.latestFxRetrievedAt,
  });

  bool get hasHistoricalCostBasis =>
      historicalCostBasisInBaseCurrency != null;

  bool get usesFx => fxEvidence.isNotEmpty;

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

/// Values the *current* market value of a portfolio in one base currency.
///
/// Current FX is allowed only for current valuation. Historical cost basis and
/// portfolio P/L remain unavailable whenever a position is denominated in a
/// different currency because ATHENA does not yet persist the acquisition-date
/// FX required for a truthful historical conversion.
///
/// The service fails closed when either market-price provenance or FX
/// provenance is incomplete. A numerical price without source and coherent
/// observation/retrieval timestamps is not sufficient evidence for an ATHENA
/// portfolio aggregate.
class PortfolioCurrentValuationService {
  final CurrentFxRateLoader loadCurrentFxRate;

  const PortfolioCurrentValuationService({
    required this.loadCurrentFxRate,
  });

  Future<PortfolioCurrentValuation> value({
    required List<PortfolioPosition> positions,
    String baseCurrency = 'EUR',
  }) async {
    final base = _normalizeCurrency(baseCurrency, 'baseCurrency');
    final fxBySourceCurrency = <String, FxQuote>{};
    final fxEvidence = <FxQuote>[];

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

      historicalCostBasisReady = false;

      var fx = fxBySourceCurrency[sourceCurrency];
      if (fx == null) {
        fx = await loadCurrentFxRate(
          baseCurrency: sourceCurrency,
          quoteCurrency: base,
        );
        _validateFxEvidence(
          fx,
          expectedBase: sourceCurrency,
          expectedQuote: base,
        );
        fxBySourceCurrency[sourceCurrency] = fx;
        fxEvidence.add(fx);
      }

      final converted = fx.convertCurrent(position.currentValue);
      if (!converted.isFinite || converted < 0) {
        throw StateError(
          'La conversión FX produjo un valor actual inválido para '
          '${position.symbol}.',
        );
      }
      currentValueInBase += converted;
    }

    if (!currentValueInBase.isFinite || currentValueInBase < 0) {
      throw StateError('El valor agregado de cartera no es finito o es negativo.');
    }

    DateTime? latestFxObservedAt;
    DateTime? latestFxRetrievedAt;
    for (final fx in fxEvidence) {
      latestFxObservedAt = _latest(latestFxObservedAt, fx.observedAt);
      latestFxRetrievedAt = _latest(latestFxRetrievedAt, fx.retrievedAt);
    }

    return PortfolioCurrentValuation(
      baseCurrency: base,
      currentValueInBaseCurrency: currentValueInBase,
      positionsValued: positions.length,
      fxEvidence: List.unmodifiable(fxEvidence),
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
    if (fx.baseCurrency != expectedBase || fx.quoteCurrency != expectedQuote) {
      throw StateError('La evidencia FX no corresponde al par solicitado.');
    }
    if (!fx.rate.isFinite || fx.rate <= 0) {
      throw StateError('La evidencia FX contiene una tasa inválida.');
    }
    if (fx.sourceProvider.trim().isEmpty) {
      throw StateError('La evidencia FX no declara proveedor.');
    }
    if (fx.sourceSymbol.trim().isEmpty) {
      throw StateError('La evidencia FX no declara símbolo fuente.');
    }
    if (fx.retrievedAt.isBefore(fx.observedAt)) {
      throw StateError('La recuperación FX precede a su observación.');
    }
    if (fx.historicalPointInTimeEligible) {
      throw StateError(
        'Una cotización FX actual no puede utilizarse como evidencia PIT histórica.',
      );
    }
  }

  String _normalizeCurrency(String value, String field) {
    final normalized = value.trim().toUpperCase();
    if (!RegExp(r'^[A-Z]{3}$').hasMatch(normalized)) {
      throw StateError('$field no contiene una moneda ISO verificable.');
    }
    return normalized;
  }

  DateTime _latest(DateTime? current, DateTime candidate) {
    if (current == null || candidate.isAfter(current)) {
      return candidate;
    }
    return current;
  }
}
