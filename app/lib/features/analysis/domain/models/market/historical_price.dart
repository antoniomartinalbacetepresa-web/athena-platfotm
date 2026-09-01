/// Precio histórico de mercado de una acción.
///
/// Representa una observación OHLCV independiente del proveedor de datos.
///
/// OHLCV:
/// - Open: precio de apertura.
/// - High: máximo.
/// - Low: mínimo.
/// - Close: precio de cierre.
/// - Volume: volumen negociado.
///
/// Este modelo no contiene indicadores técnicos ni reglas de inversión.
class HistoricalPrice {
  final DateTime date;

  final double open;
  final double high;
  final double low;
  final double close;

  final double volume;

  /// Precio de cierre ajustado cuando el proveedor lo proporciona.
  ///
  /// Puede ser null cuando no exista información ajustada.
  final double? adjustedClose;

  const HistoricalPrice({
    required this.date,
    required this.open,
    required this.high,
    required this.low,
    required this.close,
    required this.volume,
    this.adjustedClose,
  });
}