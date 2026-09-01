import 'market_region.dart';

/// Procedencia de los pesos regionales utilizados por ATHENA TYCHE.
///
/// [calculated]
/// Los pesos han sido calculados utilizando capitalizaciones de mercado
/// disponibles en el universo analizado.
///
/// [baseline]
/// No existe información suficiente para realizar el cálculo y se utiliza
/// temporalmente una distribución estructural de referencia.
///
/// En el futuro podrán añadirse nuevas procedencias, por ejemplo:
/// - historical,
/// - blended,
/// - learned.
enum RegionalMarketWeightSource {
  calculated,
  baseline,
}

/// Pesos de las regiones utilizadas por ATHENA TYCHE.
///
/// Representan la distribución relativa de capitalización entre las tres
/// grandes regiones estructurales utilizadas actualmente por la aplicación:
///
/// - América
/// - Europa
/// - Asia
///
/// IMPORTANTE:
///
/// Los pesos pueden proceder de datos observados o de un baseline.
///
/// El baseline existe para que ATHENA TYCHE pueda funcionar cuando todavía
/// no dispone de un universo suficientemente completo para calcular
/// capitalizaciones reales.
///
/// Nunca debe interpretarse el baseline como una medición en tiempo real.
class RegionalMarketWeights {
  /// Baseline estructural utilizado cuando no existe información suficiente.
  ///
  /// Es una aproximación operativa coherente con la distribución reciente
  /// de la capitalización bursátil mundial.
  ///
  /// No representa una medición en tiempo real.
  static const RegionalMarketWeights baseline =
      RegionalMarketWeights(
    america: 0.54,
    europe: 0.16,
    asia: 0.30,
    source: RegionalMarketWeightSource.baseline,
    confidence: 0.35,
  );

  final double america;
  final double europe;
  final double asia;

  /// Procedencia de los pesos.
  final RegionalMarketWeightSource source;

  /// Confianza asignada a la estimación.
  ///
  /// Debe encontrarse entre 0 y 1.
  ///
  /// Esta primera versión utiliza:
  /// - 1.0 para un cálculo realizado con datos del universo;
  /// - 0.35 para el baseline provisional.
  ///
  /// Más adelante la confianza se calculará dinámicamente utilizando:
  /// - cobertura del universo;
  /// - calidad de las fuentes;
  /// - antigüedad de los datos;
  /// - estabilidad histórica;
  /// - número de observaciones.
  final double confidence;

  const RegionalMarketWeights({
    required this.america,
    required this.europe,
    required this.asia,
    this.source = RegionalMarketWeightSource.calculated,
    this.confidence = 1.0,
  });

  /// Suma de los pesos regionales.
  double get total => america + europe + asia;

  /// Comprueba que los pesos forman una distribución válida.
  bool get isValid {
    if (!america.isFinite ||
        !europe.isFinite ||
        !asia.isFinite ||
        !confidence.isFinite) {
      return false;
    }

    if (america < 0 ||
        europe < 0 ||
        asia < 0 ||
        confidence < 0 ||
        confidence > 1) {
      return false;
    }

    return (total - 1.0).abs() <= 0.000001;
  }

  /// Indica si los pesos proceden de capitalizaciones calculadas.
  bool get isCalculated {
    return source == RegionalMarketWeightSource.calculated;
  }

  /// Indica si se está utilizando el baseline provisional.
  bool get isBaseline {
    return source == RegionalMarketWeightSource.baseline;
  }

  /// Identificador textual estable de la procedencia.
  String get sourceKey {
    switch (source) {
      case RegionalMarketWeightSource.calculated:
        return 'calculated';

      case RegionalMarketWeightSource.baseline:
        return 'baseline';
    }
  }

  /// Devuelve el peso correspondiente a una región.
  double forRegion(MarketRegion region) {
    switch (region) {
      case MarketRegion.america:
        return america;

      case MarketRegion.europe:
        return europe;

      case MarketRegion.asia:
        return asia;
    }
  }
}