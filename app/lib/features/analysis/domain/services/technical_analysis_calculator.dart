import '../models/market/historical_price.dart';
import '../models/technical_analysis_data.dart';

/// Calcula indicadores técnicos exclusivamente a partir de datos históricos.
///
/// Responsabilidades:
/// - calcular medias móviles;
/// - calcular pendientes de medias móviles;
/// - determinar la posición del precio respecto a las medias.
///
/// No contiene:
/// - recomendaciones;
/// - puntuaciones;
/// - reglas de compra o venta;
/// - análisis fundamental;
/// - noticias;
/// - datos macroeconómicos.
class TechnicalAnalysisCalculator {
  const TechnicalAnalysisCalculator();

  /// Calcula el bloque básico de análisis técnico.
  ///
  /// Las observaciones deben estar ordenadas cronológicamente,
  /// desde la más antigua hasta la más reciente.
  TechnicalAnalysisData calculate(
    List<HistoricalPrice> prices,
  ) {
    if (prices.isEmpty) {
      return const TechnicalAnalysisData();
    }

    final sortedPrices = List<HistoricalPrice>.from(prices)
      ..sort((a, b) => a.date.compareTo(b.date));

    final closes = sortedPrices
        .map((price) => price.close)
        .toList(growable: false);

    final currentPrice = closes.last;

    final sma20 = _simpleMovingAverage(closes, 20);
    final sma50 = _simpleMovingAverage(closes, 50);
    final sma200 = _simpleMovingAverage(closes, 200);

    final sma50Slope = _calculateSlope(closes, 50);
    final sma200Slope = _calculateSlope(closes, 200);

    return TechnicalAnalysisData(
      movingAverage20: sma20,
      movingAverage50: sma50,
      movingAverage200: sma200,
      priceAboveMovingAverage20:
          sma20 == null ? null : currentPrice > sma20,
      priceAboveMovingAverage50:
          sma50 == null ? null : currentPrice > sma50,
      priceAboveMovingAverage200:
          sma200 == null ? null : currentPrice > sma200,
      movingAverage50Slope: sma50Slope,
      movingAverage200Slope: sma200Slope,
      observationsUsed: sortedPrices.length,
      analysisStartDate: sortedPrices.first.date,
      analysisEndDate: sortedPrices.last.date,
    );
  }

  /// Calcula una media móvil simple.
  ///
  /// Devuelve null cuando no existen suficientes observaciones.
  double? _simpleMovingAverage(
    List<double> values,
    int period,
  ) {
    if (values.length < period) {
      return null;
    }

    var sum = 0.0;

    for (var i = values.length - period; i < values.length; i++) {
      sum += values[i];
    }

    return sum / period;
  }

  /// Calcula una pendiente aproximada de los precios de cierre
  /// dentro de las últimas [period] observaciones.
  ///
  /// El resultado representa el cambio medio por observación.
  double? _calculateSlope(
    List<double> values,
    int period,
  ) {
    if (values.length < period) {
      return null;
    }

    final startIndex = values.length - period;
    final endIndex = values.length - 1;

    final startValue = values[startIndex];
    final endValue = values[endIndex];

    final intervals = endIndex - startIndex;

    if (intervals == 0) {
      return null;
    }

    return (endValue - startValue) / intervals;
  }
}
