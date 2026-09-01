import 'dart:convert';

import '../../domain/models/stock_analysis_data.dart';
import '../mappers/fmp_stock_analysis_mapper.dart';
import 'fmp_api_client.dart';
import 'stock_market_data_source.dart';

/// Fuente de datos de Financial Modeling Prep.
///
/// Responsabilidades:
/// - Solicitar datos a FMP.
/// - Validar la respuesta recibida.
/// - Convertir la respuesta mediante el mapper.
///
/// No contiene reglas de inversión ni lógica de análisis.
class FmpStockMarketDataSource implements StockMarketDataSource {
  final FmpApiClient apiClient;
  final FmpStockAnalysisMapper mapper;

  const FmpStockMarketDataSource({
    required this.apiClient,
    this.mapper = const FmpStockAnalysisMapper(),
  });

  @override
  Future<StockAnalysisData> getStockAnalysisData(
    String symbol,
  ) async {
    final normalizedSymbol = symbol.trim().toUpperCase();

    if (normalizedSymbol.isEmpty) {
      throw ArgumentError('El símbolo de la acción no puede estar vacío.');
    }

    final response = await apiClient.getQuote(normalizedSymbol);

    if (response.statusCode != 200) {
      throw Exception(
        'FMP respondió con código HTTP ${response.statusCode}.',
      );
    }

    final dynamic decoded = jsonDecode(response.body);

    if (decoded is! List || decoded.isEmpty) {
      throw Exception(
        'FMP no devolvió datos para $normalizedSymbol.',
      );
    }

    final firstItem = decoded.first;

    if (firstItem is! Map) {
      throw Exception(
        'La respuesta de FMP tiene un formato inesperado.',
      );
    }

    final json = Map<String, dynamic>.from(firstItem);

    return mapper.fromQuote(
      symbol: normalizedSymbol,
      json: json,
    );
  }
}