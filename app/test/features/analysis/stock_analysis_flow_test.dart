import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/analysis/application/stock_analysis_service.dart';
import 'package:app/features/analysis/data/datasources/mock_stock_market_data_source.dart';
import 'package:app/features/analysis/data/repositories/stock_analysis_repository.dart';
import 'package:app/features/analysis/domain/models/stock_analysis_result.dart';
import 'package:app/features/analysis/domain/services/stock_analysis_engine.dart';

void main() {
  test(
    'El circuito nuevo obtiene datos y genera un análisis',
    () async {
      const dataSource = MockStockMarketDataSource();

      final repository = StockAnalysisRepository(
        dataSource: dataSource,
      );

      const engine = StockAnalysisEngine();

      final service = StockAnalysisService(
        repository: repository,
        engine: engine,
      );

      final StockAnalysisResult result =
          await service.analyzeStock('AAPL');

      expect(result.symbol, 'AAPL');
      expect(result.companyName, 'Empresa de prueba');
      expect(result.score, greaterThan(0));
      expect(result.confidence, greaterThan(0));
      expect(result.sources, contains('Mock'));
    },
  );
}
