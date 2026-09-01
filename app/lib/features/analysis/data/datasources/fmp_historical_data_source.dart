import 'dart:convert';

import '../../domain/models/market/historical_price.dart';
import '../mappers/fmp_historical_price_mapper.dart';
import 'fmp_api_client.dart';

/// Fuente de datos históricos de Financial Modeling Prep.
///
/// Responsabilidades:
/// - solicitar datos históricos a FMP,
/// - validar la respuesta,
/// - transformar el JSON mediante el mapper.
///
/// No contiene:
/// - indicadores técnicos,
/// - interpretación de tendencias,
/// - señales de compra o venta,
/// - puntuaciones,
/// - recomendaciones.
class FmpHistoricalDataSource {
  final FmpApiClient apiClient;
  final FmpHistoricalPriceMapper mapper;

  const FmpHistoricalDataSource({
    required this.apiClient,
    this.mapper = const FmpHistoricalPriceMapper(),
  });

  /// Obtiene el histórico diario de una acción.
  ///
  /// Devuelve los datos ordenados desde la fecha más antigua
  /// hasta la más reciente.
  Future<List<HistoricalPrice>> getHistoricalPrices(
    String symbol,
  ) async {
    final normalizedSymbol = symbol.trim().toUpperCase();

    if (normalizedSymbol.isEmpty) {
      throw ArgumentError(
        'El símbolo de la acción no puede estar vacío.',
      );
    }

    final response = await apiClient.getHistoricalPrices(
      normalizedSymbol,
    );

    if (response.statusCode != 200) {
      throw Exception(
        'FMP respondió con código HTTP ${response.statusCode}.',
      );
    }

    final dynamic decoded = jsonDecode(response.body);

    if (decoded is! Map) {
      throw Exception(
        'La respuesta histórica de FMP tiene un formato inesperado.',
      );
    }

    final historical = decoded['historical'];

    if (historical is! List) {
      throw Exception(
        'FMP no devolvió una lista histórica válida.',
      );
    }

    if (historical.isEmpty) {
      return const [];
    }

    return mapper.fromHistoricalQuotes(historical);
  }
}