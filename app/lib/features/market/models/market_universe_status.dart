class MarketUniverseStatus {
  final int activeCount;
  final int globallyUsableCount;
  final double usableCoverage;
  final Map<String, int> regionCounts;
  final bool isGlobalReady;
  final bool usingFallback;

  /// Indica si la metodología de selección actual permite utilizar el
  /// universo para inferir pesos regionales comparables.
  final bool isWeightingReady;

  /// Identificador estable de la metodología de ponderación/cobertura.
  final String weightingMethod;

  /// Estado legible para diagnóstico y trazabilidad.
  final String weightingStatus;

  const MarketUniverseStatus({
    required this.activeCount,
    required this.globallyUsableCount,
    required this.usableCoverage,
    required this.regionCounts,
    required this.isGlobalReady,
    required this.usingFallback,
    this.isWeightingReady = false,
    this.weightingMethod = 'unknown',
    this.weightingStatus = 'unknown',
  });

  const MarketUniverseStatus.fallback()
      : activeCount = 0,
        globallyUsableCount = 0,
        usableCoverage = 0,
        regionCounts = const {
          'america': 0,
          'europe': 0,
          'asia': 0,
        },
        isGlobalReady = false,
        usingFallback = true,
        isWeightingReady = false,
        weightingMethod = 'fallback',
        weightingStatus = 'fallback';

  int get americaCount => regionCounts['america'] ?? 0;
  int get europeCount => regionCounts['europe'] ?? 0;
  int get asiaCount => regionCounts['asia'] ?? 0;
}
