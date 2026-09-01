/// Resultado del análisis realizado por ATHENA TYCHE sobre una acción.
///
/// Este modelo representa la conclusión del motor de análisis.
/// No obtiene datos por sí mismo y no depende de ninguna fuente externa.
class StockAnalysisResult {
  final String symbol;
  final String companyName;

  // ===========================================================================
  // PUNTUACIÓN
  // ===========================================================================

  /// Puntuación global de 0 a 100.
  final double score;

  /// Nivel de confianza del análisis de 0 a 100.
  final double confidence;

  // ===========================================================================
  // CONCLUSIÓN
  // ===========================================================================

  final StockRecommendation recommendation;

  /// Explicación general del resultado.
  final String summary;

  // ===========================================================================
  // ÁREAS DE ANÁLISIS
  // ===========================================================================

  final AnalysisComponentResult fundamentalAnalysis;
  final AnalysisComponentResult valuationAnalysis;
  final AnalysisComponentResult growthAnalysis;
  final AnalysisComponentResult profitabilityAnalysis;
  final AnalysisComponentResult financialHealthAnalysis;
  final AnalysisComponentResult technicalAnalysis;
  final AnalysisComponentResult riskAnalysis;

  // ===========================================================================
  // RIESGOS Y PUNTOS POSITIVOS
  // ===========================================================================

  final List<String> strengths;
  final List<String> risks;

  // ===========================================================================
  // FUENTES
  // ===========================================================================

  /// Fuentes que participaron en el análisis.
  final List<String> sources;

  /// Momento en el que se realizó el análisis.
  final DateTime analysisTimestamp;

  const StockAnalysisResult({
    required this.symbol,
    required this.companyName,
    required this.score,
    required this.confidence,
    required this.recommendation,
    required this.summary,
    required this.fundamentalAnalysis,
    required this.valuationAnalysis,
    required this.growthAnalysis,
    required this.profitabilityAnalysis,
    required this.financialHealthAnalysis,
    required this.technicalAnalysis,
    required this.riskAnalysis,
    required this.strengths,
    required this.risks,
    required this.sources,
    required this.analysisTimestamp,
  });

  // ===========================================================================
  // UTILIDADES
  // ===========================================================================

  bool get isPositive {
    return score >= 60;
  }

  bool get isNegative {
    return score < 40;
  }

  bool get isNeutral {
    return score >= 40 && score < 60;
  }

  String get recommendationLabel {
    return recommendation.label;
  }

  StockAnalysisResult copyWith({
    String? symbol,
    String? companyName,
    double? score,
    double? confidence,
    StockRecommendation? recommendation,
    String? summary,
    AnalysisComponentResult? fundamentalAnalysis,
    AnalysisComponentResult? valuationAnalysis,
    AnalysisComponentResult? growthAnalysis,
    AnalysisComponentResult? profitabilityAnalysis,
    AnalysisComponentResult? financialHealthAnalysis,
    AnalysisComponentResult? technicalAnalysis,
    AnalysisComponentResult? riskAnalysis,
    List<String>? strengths,
    List<String>? risks,
    List<String>? sources,
    DateTime? analysisTimestamp,
  }) {
    return StockAnalysisResult(
      symbol: symbol ?? this.symbol,
      companyName: companyName ?? this.companyName,
      score: score ?? this.score,
      confidence: confidence ?? this.confidence,
      recommendation: recommendation ?? this.recommendation,
      summary: summary ?? this.summary,
      fundamentalAnalysis:
          fundamentalAnalysis ?? this.fundamentalAnalysis,
      valuationAnalysis:
          valuationAnalysis ?? this.valuationAnalysis,
      growthAnalysis:
          growthAnalysis ?? this.growthAnalysis,
      profitabilityAnalysis:
          profitabilityAnalysis ?? this.profitabilityAnalysis,
      financialHealthAnalysis:
          financialHealthAnalysis ?? this.financialHealthAnalysis,
      technicalAnalysis:
          technicalAnalysis ?? this.technicalAnalysis,
      riskAnalysis:
          riskAnalysis ?? this.riskAnalysis,
      strengths: strengths ?? this.strengths,
      risks: risks ?? this.risks,
      sources: sources ?? this.sources,
      analysisTimestamp:
          analysisTimestamp ?? this.analysisTimestamp,
    );
  }
}

// =============================================================================
// RECOMENDACIÓN
// =============================================================================

enum StockRecommendation {
  strongBuy,
  buy,
  hold,
  reduce,
  avoid,
}

extension StockRecommendationExtension
    on StockRecommendation {
  String get label {
    switch (this) {
      case StockRecommendation.strongBuy:
        return 'Compra fuerte';

      case StockRecommendation.buy:
        return 'Comprar';

      case StockRecommendation.hold:
        return 'Mantener';

      case StockRecommendation.reduce:
        return 'Reducir';

      case StockRecommendation.avoid:
        return 'Evitar';
    }
  }
}

// =============================================================================
// RESULTADO DE CADA ÁREA
// =============================================================================

class AnalysisComponentResult {
  /// Puntuación del componente de 0 a 100.
  final double score;

  /// Explicación de la puntuación.
  final String explanation;

  /// Indicadores positivos encontrados.
  final List<String> positives;

  /// Indicadores negativos encontrados.
  final List<String> negatives;

  const AnalysisComponentResult({
    required this.score,
    required this.explanation,
    required this.positives,
    required this.negatives,
  });

  bool get isPositive {
    return score >= 60;
  }

  bool get isNegative {
    return score < 40;
  }

  bool get isNeutral {
    return score >= 40 && score < 60;
  }
}