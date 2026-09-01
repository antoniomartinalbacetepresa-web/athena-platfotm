import '../data/repositories/stock_analysis_repository.dart';
import '../domain/models/stock_analysis_result.dart';
import '../domain/services/stock_analysis_engine.dart';

/// Orquesta la obtención de datos y su análisis.
///
/// No conoce ninguna fuente concreta.
/// No contiene reglas de análisis.
class StockAnalysisService {
  final StockAnalysisRepository repository;
  final StockAnalysisEngine engine;

  const StockAnalysisService({
    required this.repository,
    required this.engine,
  });

  Future<StockAnalysisResult> analyzeStock(String symbol) async {
    final data = await repository.getStockAnalysisData(symbol);

    return engine.analyze(data);
  }
}
