import '../models/portfolio_correlation_snapshot.dart';
import '../models/portfolio_pair_correlation.dart';
import '../models/portfolio_position.dart';

typedef PortfolioPairCorrelationLoader = Future<PortfolioPairCorrelation>
    Function({
  required int leftInstrumentId,
  required int rightInstrumentId,
  required String sourceProvider,
  required DateTime knowledgeCutoff,
  DateTime? observedFrom,
  DateTime? observedTo,
});

/// Builds descriptive pairwise correlation evidence only from canonical
/// portfolio identities and PIT historical observations.
///
/// This service deliberately does not classify risk, recommend an allocation,
/// or turn correlation into advice. Missing canonical identity, mixed market
/// providers, duplicate canonical instruments, insufficient histories, or any
/// downstream PIT contract failure make the snapshot unavailable.
class PortfolioCorrelationEvidenceService {
  final PortfolioPairCorrelationLoader loadPair;

  const PortfolioCorrelationEvidenceService({required this.loadPair});

  Future<PortfolioCorrelationSnapshot> analyze({
    required List<PortfolioPosition> positions,
    required DateTime knowledgeCutoff,
  }) async {
    if (!knowledgeCutoff.isUtc) {
      throw ArgumentError.value(
        knowledgeCutoff,
        'knowledgeCutoff',
        'Debe expresarse explícitamente en UTC.',
      );
    }
    if (positions.length < 2) {
      throw StateError(
        'La correlación de cartera requiere al menos dos posiciones.',
      );
    }

    final canonicalIds = <int>{};
    final providers = <String>{};
    for (final position in positions) {
      if (!position.hasVerifiedCanonicalIdentity) {
        throw StateError(
          'La correlación requiere identidad canónica verificable para ${position.symbol}.',
        );
      }
      final instrumentId = position.databaseInstrumentId!;
      if (!canonicalIds.add(instrumentId)) {
        throw StateError(
          'La cartera contiene exposición duplicada al mismo instrumento canónico.',
        );
      }
      final provider = position.currentPriceSourceProvider?.trim();
      if (provider == null || provider.isEmpty) {
        throw StateError(
          'La posición ${position.symbol} no conserva proveedor de mercado.',
        );
      }
      providers.add(provider);
    }
    if (providers.length != 1) {
      throw StateError(
        'La correlación requiere un mismo proveedor histórico verificable para todas las posiciones.',
      );
    }
    final sourceProvider = providers.single;

    final pairs = <PortfolioPairCorrelation>[];
    for (var leftIndex = 0; leftIndex < positions.length - 1; leftIndex++) {
      for (
        var rightIndex = leftIndex + 1;
        rightIndex < positions.length;
        rightIndex++
      ) {
        final result = await loadPair(
          leftInstrumentId: positions[leftIndex].databaseInstrumentId!,
          rightInstrumentId: positions[rightIndex].databaseInstrumentId!,
          sourceProvider: sourceProvider,
          knowledgeCutoff: knowledgeCutoff,
        );
        if (result.productionEligible ||
            result.allocationInfluence ||
            result.automaticTrading ||
            result.recommendationPolicy != 'no_advice') {
          throw StateError(
            'Una correlación descriptiva intentó alterar la política ATHENA.',
          );
        }
        pairs.add(result);
      }
    }

    if (pairs.isEmpty) {
      throw StateError('No se obtuvieron pares de correlación verificables.');
    }

    var total = 0.0;
    var minimum = 1.0;
    var maximum = -1.0;
    var minimumSampleCount = pairs.first.sampleCount;
    var latestRetrievedAt = pairs.first.latestRetrievedAt;
    for (final pair in pairs) {
      final value = pair.correlation;
      if (!value.isFinite || value < -1 || value > 1) {
        throw StateError('Una correlación de cartera no es finita o válida.');
      }
      if (pair.sourceProvider != sourceProvider ||
          !pair.knowledgeCutoff.isAtSameMomentAs(knowledgeCutoff) ||
          pair.latestRetrievedAt.isAfter(knowledgeCutoff)) {
        throw StateError(
          'La evidencia de correlación no respeta proveedor o knowledgeCutoff.',
        );
      }
      total += value;
      if (value < minimum) minimum = value;
      if (value > maximum) maximum = value;
      if (pair.sampleCount < minimumSampleCount) {
        minimumSampleCount = pair.sampleCount;
      }
      if (pair.latestRetrievedAt.isAfter(latestRetrievedAt)) {
        latestRetrievedAt = pair.latestRetrievedAt;
      }
    }

    final mean = total / pairs.length;
    if (!mean.isFinite) {
      throw StateError('La correlación media de cartera no es finita.');
    }

    return PortfolioCorrelationSnapshot(
      pairs: List.unmodifiable(pairs),
      sourceProvider: sourceProvider,
      knowledgeCutoff: knowledgeCutoff,
      meanCorrelation: mean,
      minimumCorrelation: minimum,
      maximumCorrelation: maximum,
      minimumSampleCount: minimumSampleCount,
      latestRetrievedAt: latestRetrievedAt,
    );
  }
}
