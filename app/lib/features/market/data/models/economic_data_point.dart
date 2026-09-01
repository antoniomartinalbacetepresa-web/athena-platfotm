class EconomicDataPoint {
  final String seriesId;
  final DateTime timestamp;
  final double value;
  final String providerId;

  const EconomicDataPoint({
    required this.seriesId,
    required this.timestamp,
    required this.value,
    required this.providerId,
  });
}