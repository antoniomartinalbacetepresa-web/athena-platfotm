import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/analysis/data/mappers/fmp_stock_analysis_mapper.dart';

void main() {
  test(
    'Una respuesta de FMP /stable/quote se convierte correctamente en StockAnalysisData',
    () {
      const mapper = FmpStockAnalysisMapper();

      final result = mapper.fromQuote(
        symbol: 'AAPL',
        json: {
          'symbol': 'AAPL',
          'name': 'Apple Inc.',
          'price': 305.93,
          'previousClose': 305.26,
          'changePercentage': 0.21949,
          'volume': 28229375,
          'yearHigh': 344.57,
          'yearLow': 223.78,
          'marketCap': 4493302821080,
          'priceAvg50': 309.1908,
          'priceAvg200': 280.48364,
          'timestamp': 1786737601,
        },
      );

      expect(result.symbol, 'AAPL');
      expect(result.companyName, 'Apple Inc.');

      expect(result.currentPrice, 305.93);
      expect(result.previousClose, 305.26);
      expect(result.dayChangePercent, 0.21949);

      expect(result.marketCap, 4493302821080);

      expect(result.fiftyTwoWeekHigh, 344.57);
      expect(result.fiftyTwoWeekLow, 223.78);

      expect(result.movingAverage50, 309.1908);
      expect(result.movingAverage200, 280.48364);

      expect(result.averageVolume, 28229375);

      expect(result.beta, isNull);

      expect(
        result.sources,
        contains('Financial Modeling Prep'),
      );

      expect(result.dataTimestamp, isNotNull);
    },
  );
}