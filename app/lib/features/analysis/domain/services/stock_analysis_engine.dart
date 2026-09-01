import '../models/stock_analysis_data.dart';
import '../models/stock_analysis_result.dart';

/// Motor central de análisis de ATHENA TYCHE.
///
/// Principios:
/// - No obtiene datos de Internet.
/// - No depende de un proveedor concreto.
/// - No predice precios.
/// - No considera la ausencia de datos como una señal neutra.
/// - La puntuación se calcula únicamente con áreas que tienen información.
/// - La confianza depende de la cantidad y calidad de información disponible.
/// - La recomendación debe interpretarse junto con la confianza.
class StockAnalysisEngine {
  const StockAnalysisEngine();

  StockAnalysisResult analyze(
    StockAnalysisData data,
  ) {
    final fundamental = _analyzeFundamentals(data);
    final valuation = _analyzeValuation(data);
    final growth = _analyzeGrowth(data);
    final profitability = _analyzeProfitability(data);
    final financialHealth = _analyzeFinancialHealth(data);
    final technical = _analyzeTechnical(data);
    final risk = _analyzeRisk(data);

    final score = _calculateOverallScore(
      fundamental: fundamental,
      valuation: valuation,
      growth: growth,
      profitability: profitability,
      financialHealth: financialHealth,
      technical: technical,
      risk: risk,
    );

    final confidence = _calculateConfidence(data);

    final recommendation = _calculateRecommendation(
      score: score,
      confidence: confidence,
      hasData: data.hasData,
    );

    final strengths = <String>[
      ...fundamental.positives,
      ...valuation.positives,
      ...growth.positives,
      ...profitability.positives,
      ...financialHealth.positives,
      ...technical.positives,
      ...risk.positives,
    ];

    final risks = <String>[
      ...fundamental.negatives,
      ...valuation.negatives,
      ...growth.negatives,
      ...profitability.negatives,
      ...financialHealth.negatives,
      ...technical.negatives,
      ...risk.negatives,
    ];

    return StockAnalysisResult(
      symbol: data.symbol,
      companyName: data.companyName,
      score: score,
      confidence: confidence,
      recommendation: recommendation,
      summary: _buildSummary(
        data: data,
        score: score,
        confidence: confidence,
        recommendation: recommendation,
      ),
      fundamentalAnalysis: fundamental,
      valuationAnalysis: valuation,
      growthAnalysis: growth,
      profitabilityAnalysis: profitability,
      financialHealthAnalysis: financialHealth,
      technicalAnalysis: technical,
      riskAnalysis: risk,
      strengths: _removeDuplicates(strengths),
      risks: _removeDuplicates(risks),
      sources: List.unmodifiable(data.sources),
      analysisTimestamp: DateTime.now(),
    );
  }

  // ===========================================================================
  // FUNDAMENTALES
  // ===========================================================================

  AnalysisComponentResult _analyzeFundamentals(
    StockAnalysisData data,
  ) {
    final scores = <double>[];
    final positives = <String>[];
    final negatives = <String>[];

    if (data.peRatio != null) {
      if (data.peRatio! > 0 && data.peRatio! < 20) {
        scores.add(80);
        positives.add('PER moderado');
      } else if (data.peRatio! < 30) {
        scores.add(60);
      } else {
        scores.add(35);
        negatives.add('PER elevado');
      }
    }

    if (data.freeCashFlow != null) {
      if (data.freeCashFlow! > 0) {
        scores.add(85);
        positives.add('Flujo de caja libre positivo');
      } else {
        scores.add(25);
        negatives.add('Flujo de caja libre negativo');
      }
    }

    if (data.epsGrowth != null) {
      if (data.epsGrowth! > 10) {
        scores.add(90);
        positives.add('Crecimiento sólido del beneficio por acción');
      } else if (data.epsGrowth! > 0) {
        scores.add(65);
      } else {
        scores.add(30);
        negatives.add('Beneficio por acción en descenso');
      }
    }

    return _buildComponent(
      scores: scores,
      defaultScore: 0,
      explanation:
          'Evalúa la calidad fundamental de la empresa utilizando '
          'los datos disponibles.',
      positives: positives,
      negatives: negatives,
    );
  }

  // ===========================================================================
  // VALORACIÓN
  // ===========================================================================

  AnalysisComponentResult _analyzeValuation(
    StockAnalysisData data,
  ) {
    final scores = <double>[];
    final positives = <String>[];
    final negatives = <String>[];

    if (data.peRatio != null) {
      if (data.peRatio! > 0 && data.peRatio! < 15) {
        scores.add(85);
        positives.add('Valoración por PER relativamente baja');
      } else if (data.peRatio! < 25) {
        scores.add(65);
      } else if (data.peRatio! < 40) {
        scores.add(45);
        negatives.add('Valoración exigente');
      } else {
        scores.add(25);
        negatives.add('PER muy elevado');
      }
    }

    if (data.forwardPeRatio != null) {
      if (data.forwardPeRatio! > 0 &&
          data.forwardPeRatio! < (data.peRatio ?? 100)) {
        scores.add(80);
        positives.add('PER futuro inferior al PER actual');
      } else if (data.forwardPeRatio! > 0) {
        scores.add(45);
      }
    }

    if (data.pegRatio != null) {
      if (data.pegRatio! > 0 && data.pegRatio! < 1) {
        scores.add(90);
        positives.add('PEG favorable');
      } else if (data.pegRatio! < 2) {
        scores.add(65);
      } else {
        scores.add(35);
        negatives.add('PEG elevado');
      }
    }

    return _buildComponent(
      scores: scores,
      defaultScore: 0,
      explanation:
          'Evalúa si la valoración de mercado parece razonable '
          'en relación con los indicadores disponibles.',
      positives: positives,
      negatives: negatives,
    );
  }

  // ===========================================================================
  // CRECIMIENTO
  // ===========================================================================

  AnalysisComponentResult _analyzeGrowth(
    StockAnalysisData data,
  ) {
    final scores = <double>[];
    final positives = <String>[];
    final negatives = <String>[];

    _addGrowthMetric(
      value: data.revenueGrowth,
      scores: scores,
      positives: positives,
      negatives: negatives,
      positiveMessage: 'Crecimiento de ingresos positivo',
      negativeMessage: 'Ingresos en descenso',
    );

    _addGrowthMetric(
      value: data.earningsGrowth,
      scores: scores,
      positives: positives,
      negatives: negatives,
      positiveMessage: 'Crecimiento de beneficios positivo',
      negativeMessage: 'Beneficios en descenso',
    );

    _addGrowthMetric(
      value: data.epsGrowth,
      scores: scores,
      positives: positives,
      negatives: negatives,
      positiveMessage: 'Crecimiento del EPS positivo',
      negativeMessage: 'EPS en descenso',
    );

    return _buildComponent(
      scores: scores,
      defaultScore: 0,
      explanation:
          'Evalúa la evolución reciente de ingresos, beneficios '
          'y beneficio por acción.',
      positives: positives,
      negatives: negatives,
    );
  }

  // ===========================================================================
  // RENTABILIDAD
  // ===========================================================================

  AnalysisComponentResult _analyzeProfitability(
    StockAnalysisData data,
  ) {
    final scores = <double>[];
    final positives = <String>[];
    final negatives = <String>[];

    _addMarginMetric(
      value: data.grossMargin,
      threshold: 40,
      scores: scores,
      positives: positives,
      negatives: negatives,
      positiveMessage: 'Margen bruto sólido',
      negativeMessage: 'Margen bruto reducido',
    );

    _addMarginMetric(
      value: data.operatingMargin,
      threshold: 15,
      scores: scores,
      positives: positives,
      negatives: negatives,
      positiveMessage: 'Margen operativo sólido',
      negativeMessage: 'Margen operativo reducido',
    );

    _addMarginMetric(
      value: data.profitMargin,
      threshold: 10,
      scores: scores,
      positives: positives,
      negatives: negatives,
      positiveMessage: 'Margen de beneficio saludable',
      negativeMessage: 'Margen de beneficio reducido',
    );

    _addMarginMetric(
      value: data.returnOnEquity,
      threshold: 15,
      scores: scores,
      positives: positives,
      negatives: negatives,
      positiveMessage: 'ROE atractivo',
      negativeMessage: 'ROE reducido',
    );

    return _buildComponent(
      scores: scores,
      defaultScore: 0,
      explanation:
          'Evalúa la capacidad de la empresa para generar beneficios '
          'y rentabilidad sobre sus recursos.',
      positives: positives,
      negatives: negatives,
    );
  }

  // ===========================================================================
  // SALUD FINANCIERA
  // ===========================================================================

  AnalysisComponentResult _analyzeFinancialHealth(
    StockAnalysisData data,
  ) {
    final scores = <double>[];
    final positives = <String>[];
    final negatives = <String>[];

    if (data.totalDebt != null && data.totalCash != null) {
      if (data.totalCash! > data.totalDebt!) {
        scores.add(90);
        positives.add('Caja superior a la deuda');
      } else if (data.totalCash! > data.totalDebt! * 0.5) {
        scores.add(65);
      } else {
        scores.add(35);
        negatives.add('Deuda superior a la caja disponible');
      }
    }

    if (data.debtToEquity != null) {
      if (data.debtToEquity! < 0.5) {
        scores.add(85);
        positives.add('Endeudamiento moderado');
      } else if (data.debtToEquity! < 1.5) {
        scores.add(60);
      } else {
        scores.add(30);
        negatives.add('Endeudamiento elevado');
      }
    }

    if (data.currentRatio != null) {
      if (data.currentRatio! >= 1.5) {
        scores.add(85);
        positives.add(
          'Buena capacidad para cubrir obligaciones a corto plazo',
        );
      } else if (data.currentRatio! >= 1) {
        scores.add(60);
      } else {
        scores.add(30);
        negatives.add('Ratio corriente inferior a 1');
      }
    }

    return _buildComponent(
      scores: scores,
      defaultScore: 0,
      explanation:
          'Evalúa deuda, liquidez y capacidad financiera a partir '
          'de los datos disponibles.',
      positives: positives,
      negatives: negatives,
    );
  }

  // ===========================================================================
  // ANÁLISIS TÉCNICO
  // ===========================================================================

  AnalysisComponentResult _analyzeTechnical(
    StockAnalysisData data,
  ) {
    final scores = <double>[];
    final positives = <String>[];
    final negatives = <String>[];

    if (data.currentPrice != null &&
        data.movingAverage50 != null) {
      if (data.currentPrice! > data.movingAverage50!) {
        scores.add(75);
        positives.add(
          'Precio por encima de la media móvil de 50 sesiones',
        );
      } else {
        scores.add(40);
        negatives.add(
          'Precio por debajo de la media móvil de 50 sesiones',
        );
      }
    }

    if (data.currentPrice != null &&
        data.movingAverage200 != null) {
      if (data.currentPrice! > data.movingAverage200!) {
        scores.add(85);
        positives.add(
          'Precio por encima de la media móvil de 200 sesiones',
        );
      } else {
        scores.add(35);
        negatives.add(
          'Precio por debajo de la media móvil de 200 sesiones',
        );
      }
    }

    if (data.relativeStrengthIndex != null) {
      final rsi = data.relativeStrengthIndex!;

      if (rsi >= 45 && rsi <= 65) {
        scores.add(75);
        positives.add(
          'RSI en una zona relativamente equilibrada',
        );
      } else if (rsi < 30) {
        scores.add(65);
        positives.add(
          'RSI indica posible sobreventa',
        );
      } else if (rsi > 70) {
        scores.add(35);
        negatives.add(
          'RSI indica posible sobrecompra',
        );
      } else {
        scores.add(55);
      }
    }

    return _buildComponent(
      scores: scores,
      defaultScore: 0,
      explanation:
          'Evalúa la posición actual del precio mediante los '
          'indicadores técnicos disponibles.',
      positives: positives,
      negatives: negatives,
    );
  }

  // ===========================================================================
  // RIESGO
  // ===========================================================================

  AnalysisComponentResult _analyzeRisk(
    StockAnalysisData data,
  ) {
    final scores = <double>[];
    final positives = <String>[];
    final negatives = <String>[];

    if (data.beta != null) {
      if (data.beta! <= 0.8) {
        scores.add(80);
        positives.add('Beta relativamente baja');
      } else if (data.beta! <= 1.2) {
        scores.add(60);
      } else if (data.beta! <= 1.8) {
        scores.add(45);
        negatives.add('Beta superior al mercado');
      } else {
        scores.add(25);
        negatives.add('Beta elevada');
      }
    }

    if (data.debtToEquity != null) {
      if (data.debtToEquity! < 0.5) {
        scores.add(80);
        positives.add('Nivel de deuda relativamente bajo');
      } else if (data.debtToEquity! < 1.5) {
        scores.add(60);
      } else {
        scores.add(30);
        negatives.add(
          'El nivel de deuda aumenta el riesgo financiero',
        );
      }
    }

    return _buildComponent(
      scores: scores,
      defaultScore: 0,
      explanation:
          'Evalúa los principales factores de riesgo '
          'identificables con los datos disponibles.',
      positives: positives,
      negatives: negatives,
    );
  }

  // ===========================================================================
  // PUNTUACIÓN GLOBAL
  // ===========================================================================

  double _calculateOverallScore({
    required AnalysisComponentResult fundamental,
    required AnalysisComponentResult valuation,
    required AnalysisComponentResult growth,
    required AnalysisComponentResult profitability,
    required AnalysisComponentResult financialHealth,
    required AnalysisComponentResult technical,
    required AnalysisComponentResult risk,
  }) {
    final components = <_WeightedComponent>[
      _WeightedComponent(fundamental, 0.20),
      _WeightedComponent(valuation, 0.15),
      _WeightedComponent(growth, 0.15),
      _WeightedComponent(profitability, 0.15),
      _WeightedComponent(financialHealth, 0.15),
      _WeightedComponent(technical, 0.10),
      _WeightedComponent(risk, 0.10),
    ];

    final available = components
        .where((component) => component.result.hasEvidence)
        .toList();

    if (available.isEmpty) {
      return 0;
    }

    var weightedScore = 0.0;
    var totalWeight = 0.0;

    for (final component in available) {
      weightedScore += component.result.score * component.weight;
      totalWeight += component.weight;
    }

    if (totalWeight == 0) {
      return 0;
    }

    return _clampScore(weightedScore / totalWeight);
  }

  // ===========================================================================
  // CONFIANZA
  // ===========================================================================

  double _calculateConfidence(
    StockAnalysisData data,
  ) {
    const totalMetrics = 20;

    var availableMetrics = 0;

    void check(double? value) {
      if (value != null) {
        availableMetrics++;
      }
    }

    check(data.currentPrice);
    check(data.peRatio);
    check(data.forwardPeRatio);
    check(data.pegRatio);
    check(data.revenueGrowth);
    check(data.earningsGrowth);
    check(data.epsGrowth);
    check(data.grossMargin);
    check(data.operatingMargin);
    check(data.profitMargin);
    check(data.returnOnEquity);
    check(data.totalDebt);
    check(data.totalCash);
    check(data.debtToEquity);
    check(data.currentRatio);
    check(data.freeCashFlow);
    check(data.movingAverage50);
    check(data.movingAverage200);
    check(data.relativeStrengthIndex);
    check(data.beta);

    if (availableMetrics == 0) {
      return 0;
    }

    var confidence =
        (availableMetrics / totalMetrics) * 100;

    if (data.sources.isNotEmpty) {
      confidence += 5;
    }

    if (data.sources.length >= 2) {
      confidence += 5;
    }

    return _clampScore(confidence);
  }

  // ===========================================================================
  // RECOMENDACIÓN
  // ===========================================================================

  StockRecommendation _calculateRecommendation({
    required double score,
    required double confidence,
    required bool hasData,
  }) {
    if (!hasData || confidence < 25) {
      return StockRecommendation.hold;
    }

    if (confidence < 40) {
      if (score >= 80) {
        return StockRecommendation.buy;
      }

      if (score < 40) {
        return StockRecommendation.reduce;
      }

      return StockRecommendation.hold;
    }

    if (score >= 80) {
      return StockRecommendation.strongBuy;
    }

    if (score >= 65) {
      return StockRecommendation.buy;
    }

    if (score >= 45) {
      return StockRecommendation.hold;
    }

    if (score >= 30) {
      return StockRecommendation.reduce;
    }

    return StockRecommendation.avoid;
  }

  // ===========================================================================
  // RESUMEN
  // ===========================================================================

  String _buildSummary({
    required StockAnalysisData data,
    required double score,
    required double confidence,
    required StockRecommendation recommendation,
  }) {
    if (!data.hasData) {
      return 'No hay suficiente información disponible para realizar '
          'un análisis de ${data.symbol}.';
    }

    final recommendationText =
        recommendation.label.toLowerCase();

    return 'El análisis de ${data.companyName} (${data.symbol}) '
        'produce una puntuación de ${score.toStringAsFixed(0)}/100, '
        'con una confianza del ${confidence.toStringAsFixed(0)}%, '
        'y una valoración de $recommendationText. '
        'La conclusión se basa únicamente en la información disponible '
        'y no garantiza la evolución futura de la acción.';
  }

  // ===========================================================================
  // CONSTRUCCIÓN DE COMPONENTES
  // ===========================================================================

  AnalysisComponentResult _buildComponent({
    required List<double> scores,
    required double defaultScore,
    required String explanation,
    required List<String> positives,
    required List<String> negatives,
  }) {
    if (scores.isEmpty) {
      return AnalysisComponentResult(
        score: defaultScore,
        explanation:
            '$explanation No existen suficientes datos específicos '
            'para valorar esta área.',
        positives: List.unmodifiable(positives),
        negatives: List.unmodifiable(negatives),
      );
    }

    final average =
        scores.reduce((a, b) => a + b) / scores.length;

    return AnalysisComponentResult(
      score: _clampScore(average),
      explanation: explanation,
      positives: List.unmodifiable(positives),
      negatives: List.unmodifiable(negatives),
    );
  }

  // ===========================================================================
  // MÉTRICAS DE CRECIMIENTO
  // ===========================================================================

  void _addGrowthMetric({
    required double? value,
    required List<double> scores,
    required List<String> positives,
    required List<String> negatives,
    required String positiveMessage,
    required String negativeMessage,
  }) {
    if (value == null) {
      return;
    }

    if (value >= 15) {
      scores.add(90);
      positives.add(positiveMessage);
    } else if (value >= 5) {
      scores.add(75);
    } else if (value >= 0) {
      scores.add(60);
    } else if (value >= -5) {
      scores.add(40);
    } else {
      scores.add(20);
      negatives.add(negativeMessage);
    }
  }

  // ===========================================================================
  // MÉTRICAS DE RENTABILIDAD
  // ===========================================================================

  void _addMarginMetric({
    required double? value,
    required double threshold,
    required List<double> scores,
    required List<String> positives,
    required List<String> negatives,
    required String positiveMessage,
    required String negativeMessage,
  }) {
    if (value == null) {
      return;
    }

    if (value >= threshold * 1.5) {
      scores.add(90);
      positives.add(positiveMessage);
    } else if (value >= threshold) {
      scores.add(75);
    } else if (value >= threshold * 0.5) {
      scores.add(55);
    } else if (value >= 0) {
      scores.add(35);
    } else {
      scores.add(20);
      negatives.add(negativeMessage);
    }
  }

  // ===========================================================================
  // UTILIDADES
  // ===========================================================================

  double _clampScore(double value) {
    if (value < 0) {
      return 0;
    }

    if (value > 100) {
      return 100;
    }

    return value;
  }

  List<String> _removeDuplicates(
    List<String> values,
  ) {
    return List.unmodifiable(
      values.toSet().toList(),
    );
  }
}

/// Relación entre un área de análisis y su peso.
class _WeightedComponent {
  final AnalysisComponentResult result;
  final double weight;

  const _WeightedComponent(
    this.result,
    this.weight,
  );
}

extension _AnalysisComponentResultEvidence
    on AnalysisComponentResult {
  bool get hasEvidence {
    return positives.isNotEmpty ||
        negatives.isNotEmpty ||
        score != 0;
  }
}