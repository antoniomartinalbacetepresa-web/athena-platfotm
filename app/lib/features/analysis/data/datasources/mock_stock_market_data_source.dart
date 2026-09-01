import '../../domain/models/stock_analysis_data.dart';
import 'stock_market_data_source.dart';

/// Fuente temporal para comprobar el circuito de análisis.
///
/// No representa datos reales de mercado.
/// Será sustituida posteriormente por una fuente real.
class MockStockMarketDataSource implements StockMarketDataSource {
  const MockStockMarketDataSource();

  @override
  Future<StockAnalysisData> getStockAnalysisData(
    String symbol,
  ) async {
    return StockAnalysisData(
      symbol: symbol,
      companyName: 'Empresa de prueba',
      currentPrice: 100,
      previousClose: 98,
      peRatio: 18,
      forwardPeRatio: 16,
      pegRatio: 1.2,
      revenueGrowth: 12,
      earningsGrowth: 15,
      epsGrowth: 14,
      grossMargin: 45,
      operatingMargin: 18,
      profitMargin: 12,
      returnOnEquity: 18,
      returnOnAssets: 8,
      totalDebt: 500,
      totalCash: 700,
      debtToEquity: 0.7,
      currentRatio: 1.8,
      freeCashFlow: 300,
      movingAverage50: 95,
      movingAverage200: 90,
      relativeStrengthIndex: 55,
      beta: 1.1,
      sources: const ['Mock'],
      dataTimestamp: null,
    );
  }
}
