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

  /// Moneda declarada por la fuente para la cotización, por ejemplo USD o EUR.
  final String? currency;

  /// Mercado/listing declarado por la fuente.
  final String? exchange;

  /// Tipo de instrumento declarado por la fuente, cuando está disponible.
  final String? quoteType;

  /// Zona horaria del mercado declarado por la fuente.
  final String? exchangeTimezone;

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
    this.currency,
    this.exchange,
    this.quoteType,
    this.exchangeTimezone,
    required this.providerId,
    this.sourceProvider,
    this.retrievedAt,
  });
}
