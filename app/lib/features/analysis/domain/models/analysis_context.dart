/// Contexto utilizado por el motor para interpretar los datos
/// de una empresa antes de generar una recomendación.
///
/// La idea es que ATHENA TYCHE no interprete cada indicador
/// de forma aislada, sino teniendo en cuenta el contexto.
class AnalysisContext {
  /// Sector de la empresa.
  final String? sector;

  /// Industria de la empresa.
  final String? industry;

  /// País de la empresa.
  final String? country;

  /// Indica si existe información suficiente.
  final bool hasEnoughData;

  /// Número de métricas disponibles.
  final int availableMetrics;

  /// Número total de métricas que el motor esperaba comprobar.
  final int totalMetrics;

  /// Porcentaje de información disponible.
  final double dataCompleteness;

  /// Fuentes disponibles.
  final List<String> sources;

  const AnalysisContext({
    this.sector,
    this.industry,
    this.country,
    required this.hasEnoughData,
    required this.availableMetrics,
    required this.totalMetrics,
    required this.dataCompleteness,
    this.sources = const [],
  });

  bool get hasMultipleSources {
    return sources.length >= 2;
  }

  bool get hasReliableDataCoverage {
    return dataCompleteness >= 70;
  }
}