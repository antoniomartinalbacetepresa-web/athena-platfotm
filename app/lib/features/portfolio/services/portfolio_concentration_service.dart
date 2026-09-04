import '../models/portfolio_concentration_snapshot.dart';
import '../models/portfolio_position.dart';
import 'portfolio_current_valuation_service.dart';

typedef SinglePositionValuationLoader = Future<PortfolioCurrentValuation>
    Function({
  required List<PortfolioPosition> positions,
  required String baseCurrency,
});

/// Computes concentration only from verified per-position valuations in one
/// base currency.
///
/// The service deliberately does not infer correlation, diversification labels,
/// allocation readiness or advice. Those require additional verified evidence.
class PortfolioConcentrationService {
  final SinglePositionValuationLoader loadValuation;

  const PortfolioConcentrationService({required this.loadValuation});

  Future<PortfolioConcentrationSnapshot> analyze({
    required List<PortfolioPosition> positions,
    String baseCurrency = 'EUR',
  }) async {
    final base = _normalizeCurrency(baseCurrency);
    if (positions.isEmpty) {
      throw StateError('La concentración requiere al menos una posición.');
    }

    final seenSymbols = <String>{};
    final valued = <({String symbol, double value})>[];
    var total = 0.0;

    for (final position in positions) {
      final symbol = position.symbol.trim().toUpperCase();
      if (symbol.isEmpty) {
        throw StateError('La cartera contiene una posición sin símbolo.');
      }
      if (!seenSymbols.add(symbol)) {
        throw StateError(
          'La cartera contiene un símbolo duplicado y no puede agregarse de forma segura: $symbol.',
        );
      }

      final valuation = await loadValuation(
        positions: [position],
        baseCurrency: base,
      );
      if (valuation.positionsValued != 1 || valuation.baseCurrency != base) {
        throw StateError(
          'La valoración individual de $symbol no respeta el contrato solicitado.',
        );
      }

      final value = valuation.currentValueInBaseCurrency;
      if (!value.isFinite || value <= 0) {
        throw StateError(
          'La valoración individual de $symbol no es finita y positiva.',
        );
      }
      total += value;
      valued.add((symbol: symbol, value: value));
    }

    if (!total.isFinite || total <= 0) {
      throw StateError('El valor agregado verificable de la cartera es inválido.');
    }

    var hhi = 0.0;
    var largestWeight = -1.0;
    var largestSymbol = '';
    final weightedPositions = <PortfolioConcentrationPosition>[];

    for (final item in valued) {
      final weight = item.value / total;
      if (!weight.isFinite || weight <= 0 || weight > 1) {
        throw StateError('Se obtuvo un peso de cartera inválido.');
      }
      hhi += weight * weight;
      if (weight > largestWeight) {
        largestWeight = weight;
        largestSymbol = item.symbol;
      }
      weightedPositions.add(
        PortfolioConcentrationPosition(
          symbol: item.symbol,
          currentValueInBaseCurrency: item.value,
          weight: weight,
        ),
      );
    }

    if (!hhi.isFinite || hhi <= 0 || hhi > 1.000000000001) {
      throw StateError('El índice de concentración resultante es inválido.');
    }
    final effectiveCount = 1 / hhi;
    if (!effectiveCount.isFinite || effectiveCount < 1) {
      throw StateError('El número efectivo de posiciones resultante es inválido.');
    }

    return PortfolioConcentrationSnapshot(
      baseCurrency: base,
      totalCurrentValue: total,
      positions: List.unmodifiable(weightedPositions),
      concentrationIndex: hhi,
      effectivePositionCount: effectiveCount,
      largestPositionSymbol: largestSymbol,
      largestPositionWeight: largestWeight,
    );
  }

  String _normalizeCurrency(String value) {
    final normalized = value.trim().toUpperCase();
    if (!RegExp(r'^[A-Z]{3}$').hasMatch(normalized)) {
      throw StateError('La moneda base no es una moneda ISO verificable.');
    }
    return normalized;
  }
}
