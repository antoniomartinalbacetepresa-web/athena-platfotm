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

  /// Identificador del adaptador que entrega el dato a Flutter.
  final String providerId;

  /// Proveedor externo real declarado por el backend, cuando está disponible.
  final String? sourceProvider;

  /// Momento en que el backend recuperó la evidencia desde la fuente externa.
  final DateTime? retrievedAt;

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
    this.sourceProvider,
    this.retrievedAt,
  });
}
