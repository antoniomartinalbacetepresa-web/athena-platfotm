import '../models/portfolio_allocation_plan.dart';
import '../models/portfolio_allocation_target.dart';

class PortfolioAllocationPlanService {
  static const double _weightTolerance = 1e-9;

  const PortfolioAllocationPlanService();

  PortfolioAllocationPlan build({
    required double referenceCapital,
    required List<PortfolioAllocationTarget> targets,
  }) {
    if (!referenceCapital.isFinite || referenceCapital <= 0) {
      throw ArgumentError.value(
        referenceCapital,
        'referenceCapital',
        'El capital de referencia debe ser finito y mayor que cero.',
      );
    }

    if (targets.isEmpty) {
      throw StateError(
        'No existen objetivos validados para construir una asignación.',
      );
    }

    final seenSymbols = <String>{};
    final lines = <PortfolioAllocationLine>[];
    var totalWeight = 0.0;

    for (final target in targets) {
      final symbol = target.symbol.trim().toUpperCase();
      final recommendationId = target.sourceRecommendationId.trim();
      final fingerprint = target.evidenceFingerprint.trim();

      if (!target.productionEligible) {
        throw StateError(
          'La asignación está bloqueada: $symbol no es elegible para producción.',
        );
      }

      if (symbol.isEmpty) {
        throw StateError('Un objetivo de asignación no tiene símbolo válido.');
      }

      if (!seenSymbols.add(symbol)) {
        throw StateError('Objetivo duplicado para $symbol.');
      }

      if (recommendationId.isEmpty || fingerprint.isEmpty) {
        throw StateError(
          'La asignación de $symbol carece de trazabilidad suficiente.',
        );
      }

      final weight = target.targetWeight;
      if (!weight.isFinite || weight < 0 || weight > 1) {
        throw StateError('Peso objetivo inválido para $symbol.');
      }

      totalWeight += weight;
      if (totalWeight > 1 + _weightTolerance) {
        throw StateError(
          'La suma de pesos objetivo supera el 100 % del capital.',
        );
      }

      lines.add(
        PortfolioAllocationLine(
          symbol: symbol,
          targetWeight: weight,
          targetAmount: referenceCapital * weight,
          sourceRecommendationId: recommendationId,
          evidenceFingerprint: fingerprint,
        ),
      );
    }

    final boundedWeight = totalWeight.clamp(0.0, 1.0).toDouble();
    final allocatedAmount = referenceCapital * boundedWeight;
    final cashReserveAmount = referenceCapital - allocatedAmount;

    return PortfolioAllocationPlan(
      referenceCapital: referenceCapital,
      lines: List.unmodifiable(lines),
      allocatedAmount: allocatedAmount,
      cashReserveAmount: cashReserveAmount,
      cashReserveWeight: 1.0 - boundedWeight,
    );
  }
}
