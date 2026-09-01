import '../../domain/models/stock_analysis_data.dart';

/// Contrato que debe cumplir cualquier fuente de datos de mercado.
///
/// La fuente concreta no debe contener lógica de análisis.
/// Su única responsabilidad es obtener y devolver datos.
abstract interface class StockMarketDataSource {
  Future<StockAnalysisData> getStockAnalysisData(String symbol);
}
