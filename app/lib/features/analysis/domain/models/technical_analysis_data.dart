/// Resultado del análisis técnico de una acción.
///
/// Este modelo representa únicamente información derivada del histórico
/// de precios y volumen.
///
/// No contiene:
/// - recomendaciones de compra o venta,
/// - puntuación global,
/// - análisis fundamental,
/// - noticias,
/// - datos macroeconómicos.
///
/// Su función es proporcionar al motor general de ATHENA TYCHE
/// información objetiva sobre tendencia, momentum, volumen,
//  volatilidad y estructura del precio.
class TechnicalAnalysisData {
  // ===========================================================================
  // TENDENCIA
  // ===========================================================================

  /// Media móvil simple de 20 sesiones.
  final double? movingAverage20;

  /// Media móvil simple de 50 sesiones.
  final double? movingAverage50;

  /// Media móvil simple de 200 sesiones.
  final double? movingAverage200;

  /// Indica si el precio está por encima de la SMA20.
  final bool? priceAboveMovingAverage20;

  /// Indica si el precio está por encima de la SMA50.
  final bool? priceAboveMovingAverage50;

  /// Indica si el precio está por encima de la SMA200.
  final bool? priceAboveMovingAverage200;

  /// Pendiente aproximada de la SMA50.
  ///
  /// Positiva = tendencia creciente.
  /// Negativa = tendencia decreciente.
  final double? movingAverage50Slope;

  /// Pendiente aproximada de la SMA200.
  final double? movingAverage200Slope;

  // ===========================================================================
  // MOMENTUM
  // ===========================================================================

  /// RSI de 14 sesiones.
  final double? relativeStrengthIndex;

  /// MACD.
  final double? macd;

  /// Línea de señal del MACD.
  final double? macdSignal;

  /// Histograma del MACD.
  final double? macdHistogram;

  /// Indica si el MACD está por encima de su señal.
  final bool? macdAboveSignal;

  // ===========================================================================
  // VOLUMEN
  // ===========================================================================

  /// Volumen medio de las últimas 20 sesiones.
  final double? averageVolume20;

  /// Volumen relativo respecto a la media de 20 sesiones.
  ///
  /// 1.0 = volumen normal.
  /// > 1.0 = volumen superior a la media.
  /// < 1.0 = volumen inferior a la media.
  final double? relativeVolume;

  // ===========================================================================
  // VOLATILIDAD
  // ===========================================================================

  /// Volatilidad histórica anualizada.
  final double? historicalVolatility;

  /// ATR de 14 sesiones.
  final double? averageTrueRange14;

  // ===========================================================================
  // ESTRUCTURA DEL PRECIO
  // ===========================================================================

  /// Máximo registrado dentro del período analizado.
  final double? periodHigh;

  /// Mínimo registrado dentro del período analizado.
  final double? periodLow;

  /// Distancia porcentual respecto al máximo del período.
  final double? distanceFromPeriodHighPercent;

  /// Distancia porcentual respecto al mínimo del período.
  final double? distanceFromPeriodLowPercent;

  /// Soporte estimado más relevante.
  final double? supportLevel;

  /// Resistencia estimada más relevante.
  final double? resistanceLevel;

  // ===========================================================================
  // INFORMACIÓN TEMPORAL
  // ===========================================================================

  /// Número de observaciones utilizadas para realizar el análisis.
  final int observationsUsed;

  /// Fecha de la primera observación utilizada.
  final DateTime? analysisStartDate;

  /// Fecha de la última observación utilizada.
  final DateTime? analysisEndDate;

  const TechnicalAnalysisData({
    this.movingAverage20,
    this.movingAverage50,
    this.movingAverage200,
    this.priceAboveMovingAverage20,
    this.priceAboveMovingAverage50,
    this.priceAboveMovingAverage200,
    this.movingAverage50Slope,
    this.movingAverage200Slope,
    this.relativeStrengthIndex,
    this.macd,
    this.macdSignal,
    this.macdHistogram,
    this.macdAboveSignal,
    this.averageVolume20,
    this.relativeVolume,
    this.historicalVolatility,
    this.averageTrueRange14,
    this.periodHigh,
    this.periodLow,
    this.distanceFromPeriodHighPercent,
    this.distanceFromPeriodLowPercent,
    this.supportLevel,
    this.resistanceLevel,
    this.observationsUsed = 0,
    this.analysisStartDate,
    this.analysisEndDate,
  });

  // ===========================================================================
  // UTILIDADES
  // ===========================================================================

  /// Indica si existe información técnica suficiente para algún análisis.
  bool get hasData {
    return movingAverage20 != null ||
        movingAverage50 != null ||
        movingAverage200 != null ||
        relativeStrengthIndex != null ||
        macd != null ||
        averageVolume20 != null ||
        historicalVolatility != null ||
        averageTrueRange14 != null ||
        supportLevel != null ||
        resistanceLevel != null;
  }

  /// Crea una copia modificando únicamente los valores indicados.
  TechnicalAnalysisData copyWith({
    double? movingAverage20,
    double? movingAverage50,
    double? movingAverage200,
    bool? priceAboveMovingAverage20,
    bool? priceAboveMovingAverage50,
    bool? priceAboveMovingAverage200,
    double? movingAverage50Slope,
    double? movingAverage200Slope,
    double? relativeStrengthIndex,
    double? macd,
    double? macdSignal,
    double? macdHistogram,
    bool? macdAboveSignal,
    double? averageVolume20,
    double? relativeVolume,
    double? historicalVolatility,
    double? averageTrueRange14,
    double? periodHigh,
    double? periodLow,
    double? distanceFromPeriodHighPercent,
    double? distanceFromPeriodLowPercent,
    double? supportLevel,
    double? resistanceLevel,
    int? observationsUsed,
    DateTime? analysisStartDate,
    DateTime? analysisEndDate,
  }) {
    return TechnicalAnalysisData(
      movingAverage20:
          movingAverage20 ?? this.movingAverage20,
      movingAverage50:
          movingAverage50 ?? this.movingAverage50,
      movingAverage200:
          movingAverage200 ?? this.movingAverage200,
      priceAboveMovingAverage20:
          priceAboveMovingAverage20 ??
              this.priceAboveMovingAverage20,
      priceAboveMovingAverage50:
          priceAboveMovingAverage50 ??
              this.priceAboveMovingAverage50,
      priceAboveMovingAverage200:
          priceAboveMovingAverage200 ??
              this.priceAboveMovingAverage200,
      movingAverage50Slope:
          movingAverage50Slope ??
              this.movingAverage50Slope,
      movingAverage200Slope:
          movingAverage200Slope ??
              this.movingAverage200Slope,
      relativeStrengthIndex:
          relativeStrengthIndex ??
              this.relativeStrengthIndex,
      macd: macd ?? this.macd,
      macdSignal:
          macdSignal ?? this.macdSignal,
      macdHistogram:
          macdHistogram ?? this.macdHistogram,
      macdAboveSignal:
          macdAboveSignal ?? this.macdAboveSignal,
      averageVolume20:
          averageVolume20 ?? this.averageVolume20,
      relativeVolume:
          relativeVolume ?? this.relativeVolume,
      historicalVolatility:
          historicalVolatility ??
              this.historicalVolatility,
      averageTrueRange14:
          averageTrueRange14 ??
              this.averageTrueRange14,
      periodHigh:
          periodHigh ?? this.periodHigh,
      periodLow:
          periodLow ?? this.periodLow,
      distanceFromPeriodHighPercent:
          distanceFromPeriodHighPercent ??
              this.distanceFromPeriodHighPercent,
      distanceFromPeriodLowPercent:
          distanceFromPeriodLowPercent ??
              this.distanceFromPeriodLowPercent,
      supportLevel:
          supportLevel ?? this.supportLevel,
      resistanceLevel:
          resistanceLevel ?? this.resistanceLevel,
      observationsUsed:
          observationsUsed ?? this.observationsUsed,
      analysisStartDate:
          analysisStartDate ?? this.analysisStartDate,
      analysisEndDate:
          analysisEndDate ?? this.analysisEndDate,
    );
  }
}