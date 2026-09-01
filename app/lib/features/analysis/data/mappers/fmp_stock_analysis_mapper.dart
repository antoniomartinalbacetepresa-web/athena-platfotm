import '../../domain/models/stock_analysis_data.dart';

/// Convierte respuestas del endpoint /stable/quote de Financial Modeling Prep
/// en el modelo independiente de proveedor utilizado por ATHENA TYCHE.
///
/// Responsabilidad:
/// - Leer los campos proporcionados por FMP.
/// - Convertir tipos cuando sea necesario.
/// - Construir StockAnalysisData.
///
/// No contiene:
/// - reglas de inversión,
/// - puntuaciones,
/// - señales,
/// - recomendaciones,
/// - lógica de análisis.
class FmpStockAnalysisMapper {
  const FmpStockAnalysisMapper();

  StockAnalysisData fromQuote({
    required String symbol,
    required Map<String, dynamic> json,
  }) {
    return StockAnalysisData(
      symbol: _string(json['symbol']) ?? symbol,
      companyName: _string(json['name']) ?? symbol,

      // =====================================================================
      // PRECIO Y MERCADO
      // =====================================================================

      currentPrice: _double(json['price']),
      previousClose: _double(json['previousClose']),
      marketCap: _double(json['marketCap']),

      dayChangePercent: _double(json['changePercentage']),

      // =====================================================================
      // INDICADORES DISPONIBLES EN QUOTE
      // =====================================================================

      fiftyTwoWeekHigh: _double(json['yearHigh']),
      fiftyTwoWeekLow: _double(json['yearLow']),

      movingAverage50: _double(json['priceAvg50']),
      movingAverage200: _double(json['priceAvg200']),

      averageVolume: _double(json['volume']),

      // FMP no está proporcionando beta en la respuesta /stable/quote
      // que hemos probado actualmente.
      beta: _double(json['beta']),

      // =====================================================================
      // INFORMACIÓN ADICIONAL
      // =====================================================================

      dataTimestamp: _timestamp(json['timestamp']),
      sources: const ['Financial Modeling Prep'],
    );
  }

  double? _double(dynamic value) {
    if (value is num) {
      return value.toDouble();
    }

    if (value is String) {
      return double.tryParse(value);
    }

    return null;
  }

  String? _string(dynamic value) {
    if (value is String && value.trim().isNotEmpty) {
      return value.trim();
    }

    return null;
  }

  DateTime? _timestamp(dynamic value) {
    if (value is num) {
      return DateTime.fromMillisecondsSinceEpoch(
        value.toInt() * 1000,
        isUtc: true,
      );
    }

    if (value is String) {
      final seconds = int.tryParse(value);

      if (seconds != null) {
        return DateTime.fromMillisecondsSinceEpoch(
          seconds * 1000,
          isUtc: true,
        );
      }

      return DateTime.tryParse(value);
    }

    return null;
  }
}