/// Contexto agregado de una región concreta del mercado.
///
/// Representa el estado observable de una región:
/// - América
/// - Europa
/// - Asia
///
/// Este modelo describe comportamiento de mercado.
/// No contiene el peso de la región dentro del mercado global.
///
/// El peso global se calcula posteriormente en una capa específica
/// utilizando datos reales de capitalización del universo de mercado.
///
/// No contiene lógica de inversión ni genera recomendaciones.
class RegionalMarketContext {
  /// Identificador interno de la región.
  final String region;

  /// Nombre que se mostrará al usuario.
  final String displayName;

  /// Número de activos o benchmarks considerados.
  final int assetsAnalyzed;

  /// Porcentaje de activos que están subiendo.
  final double advancingPercentage;

  /// Porcentaje de activos que están bajando.
  final double decliningPercentage;

  /// Sesgo agregado de la región.
  ///
  /// Valores previstos:
  /// - positive
  /// - neutral
  /// - negative
  final String sentiment;

  /// Resumen comprensible del estado regional.
  final String summary;

  /// Momento de actualización del contexto.
  final DateTime updatedAt;

  const RegionalMarketContext({
    required this.region,
    required this.displayName,
    required this.assetsAnalyzed,
    required this.advancingPercentage,
    required this.decliningPercentage,
    required this.sentiment,
    required this.summary,
    required this.updatedAt,
  });
}