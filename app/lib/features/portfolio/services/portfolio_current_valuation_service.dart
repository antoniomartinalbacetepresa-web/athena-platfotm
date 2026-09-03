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

  const PortfolioCurrentValuation({
    required this.baseCurrency,
    required this.currentValueInBaseCurrency,
    required this.positionsValued,
    required this.fxEvidence,
    required this.historicalCostBasisInBaseCurrency,
  });

  bool get hasHistoricalCostBasis =>
      historicalCostBasisInBaseCurrency != null;

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

    for (final position in positions) {
      _validatePositionEconomics(position);
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

    return PortfolioCurrentValuation(
      baseCurrency: base,
      currentValueInBaseCurrency: currentValueInBase,
      positionsValued: positions.length,
      fxEvidence: List.unmodifiable(fxEvidence),
      historicalCostBasisInBaseCurrency:
          historicalCostBasisReady ? historicalCostBasisInBase : null,
    );
  }

  void _validatePositionEconomics(PortfolioPosition position) {
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
}
