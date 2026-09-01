/// Contexto agregado del estado general del mercado.
///
/// Representa información de mercado a nivel global o agregado.
/// No representa una acción individual.
///
/// Este modelo no contiene lógica de inversión ni reglas
/// de recomendación.
class MarketContext {
  /// Momento en el que se actualizó el contexto.
  final DateTime updatedAt;

  /// Número de activos considerados en el contexto.
  final int assetsAnalyzed;

  /// Porcentaje de activos que están subiendo.
  final double advancingPercentage;

  /// Porcentaje de activos que están bajando.
  final double decliningPercentage;

  /// Indicador agregado de volatilidad del mercado.
  ///
  /// Puede ser null cuando el proveedor todavía no disponga
  /// de este dato.
  final double? volatility;

  /// Estado agregado del mercado.
  ///
  /// Valores previstos:
  /// - positive
  /// - neutral
  /// - negative
  final String sentiment;

  /// Texto breve y comprensible que resume el estado del mercado.
  final String summary;

  const MarketContext({
    required this.updatedAt,
    required this.assetsAnalyzed,
    required this.advancingPercentage,
    required this.decliningPercentage,
    required this.volatility,
    required this.sentiment,
    required this.summary,
  });
}