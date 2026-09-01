import '../../domain/models/stock_analysis_data.dart';
import '../datasources/stock_market_data_source.dart';

/// Punto de entrada de datos para la capa de dominio.
///
/// El repositorio desacopla el motor de análisis de las fuentes externas.
class StockAnalysisRepository {
  final StockMarketDataSource dataSource;

  const StockAnalysisRepository({
    required this.dataSource,
  });

  Future<StockAnalysisData> getStockAnalysisData(
    String symbol,
  ) {
    return dataSource.getStockAnalysisData(symbol);
  }
}
