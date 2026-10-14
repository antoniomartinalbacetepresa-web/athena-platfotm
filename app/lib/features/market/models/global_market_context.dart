import 'market_universe_status.dart';
import 'regional_market_context.dart';
import 'regional_market_weights.dart';

/// Contexto agregado del mercado global.
///
/// Combina los contextos regionales de América, Europa y Asia.
///
/// Los pesos regionales pueden proceder:
///
/// - del cálculo realizado con capitalizaciones disponibles; o
/// - de un baseline estructural cuando todavía no existen datos suficientes.
///
/// La procedencia y confianza quedan registradas para evitar presentar una
/// estimación provisional como si fuera una medición observada.
///
/// Este modelo no contiene lógica de inversión ni recomendaciones.
class GlobalMarketContext {
  final DateTime updatedAt;

  final RegionalMarketContext america;
  final RegionalMarketContext europe;
  final RegionalMarketContext asia;

  final double americaWeight;
  final double europeWeight;
  final double asiaWeight;

  /// Procedencia de los pesos regionales.
  final RegionalMarketWeightSource weightSource;

  /// Confianza de los pesos regionales utilizados.
  ///
  /// Valor comprendido entre 0 y 1.
  final double weightConfidence;

  /// Estado de calidad del universo que respalda los pesos.
  final MarketUniverseStatus marketUniverseStatus;

  final double advancingPercentage;
  final double decliningPercentage;

  /// Valores:
  /// - positive
  /// - neutral
  /// - negative
  final String sentiment;

  final String summary;

  const GlobalMarketContext({
    required this.updatedAt,
    required this.america,
    required this.europe,
    required this.asia,
    required this.americaWeight,
    required this.europeWeight,
    required this.asiaWeight,
    this.weightSource = RegionalMarketWeightSource.calculated,
    this.weightConfidence = 1.0,
    this.marketUniverseStatus = const MarketUniverseStatus.fallback(),
    required this.advancingPercentage,
    required this.decliningPercentage,
    required this.sentiment,
    required this.summary,
  });

  /// Indica si la distribución regional procede del cálculo con datos.
  bool get hasCalculatedWeights {
    return weightSource == RegionalMarketWeightSource.calculated;
  }

  /// Indica si se está utilizando temporalmente el baseline.
  bool get isUsingBaselineWeights {
    return weightSource == RegionalMarketWeightSource.baseline;
  }

  /// Indica si el backend considera listo el universo persistido real.
  bool get hasRealMarketUniverse {
    return marketUniverseStatus.isGlobalReady &&
        !marketUniverseStatus.usingFallback;
  }

  String get weightSourceKey {
    switch (weightSource) {
      case RegionalMarketWeightSource.calculated:
        return 'calculated';

      case RegionalMarketWeightSource.baseline:
        return 'baseline';
    }
  }
}
