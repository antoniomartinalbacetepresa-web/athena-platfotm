class MarketUniverseStatus {
  final int activeCount;
  final int globallyUsableCount;
  final double usableCoverage;
  final Map<String, int> regionCounts;
  final bool isGlobalReady;
  final bool usingFallback;

  const MarketUniverseStatus({
    required this.activeCount,
    required this.globallyUsableCount,
    required this.usableCoverage,
    required this.regionCounts,
    required this.isGlobalReady,
    required this.usingFallback,
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
        usingFallback = true;

  int get americaCount => regionCounts['america'] ?? 0;
  int get europeCount => regionCounts['europe'] ?? 0;
  int get asiaCount => regionCounts['asia'] ?? 0;
}
