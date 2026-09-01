class MarketDataPoint {
  final String symbol;
  final DateTime timestamp;

  final double? open;
  final double? high;
  final double? low;
  final double? close;
  final double? adjustedClose;
  final double? volume;

  /// Variación absoluta respecto al cierre anterior.
  final double? change;

  /// Variación porcentual respecto al cierre anterior.
  final double? changePercentage;

  final String providerId;

  const MarketDataPoint({
    required this.symbol,
    required this.timestamp,
    this.open,
    this.high,
    this.low,
    this.close,
    this.adjustedClose,
    this.volume,
    this.change,
    this.changePercentage,
    required this.providerId,
  });
}
