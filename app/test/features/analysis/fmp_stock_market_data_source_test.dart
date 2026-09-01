import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:app/features/analysis/data/datasources/fmp_api_client.dart';
import 'package:app/features/analysis/data/datasources/fmp_stock_market_data_source.dart';
import 'package:app/features/analysis/data/mappers/fmp_stock_analysis_mapper.dart';

class FakeHttpClient extends http.BaseClient {
  final http.Response response;

  FakeHttpClient(this.response);

  @override
  Future<http.StreamedResponse> send(
    http.BaseRequest request,
  ) async {
    return http.StreamedResponse(
      Stream<List<int>>.fromIterable(
        [response.bodyBytes],
      ),
      response.statusCode,
      headers: response.headers,
      request: request,
    );
  }
}

void main() {
  test(
    'FmpStockMarketDataSource transforma correctamente una respuesta de FMP',
    () async {
      final fakeResponse = http.Response(
        '''
[
  {
    "symbol": "AAPL",
    "name": "Apple Inc.",
    "price": 305.93,
    "previousClose": 305.26,
    "changePercentage": 0.21949,
    "volume": 28229375,
    "yearHigh": 344.57,
    "yearLow": 223.78,
    "marketCap": 4493302821080,
    "priceAvg50": 309.1908,
    "priceAvg200": 280.48364,
    "exchange": "NASDAQ",
    "open": 306.028,
    "timestamp": 1786737601
  }
]
''',
        200,
        headers: {
          'content-type': 'application/json',
        },
      );

      final httpClient = FakeHttpClient(fakeResponse);

      final apiClient = FmpApiClient(
        apiKey: 'TEST_API_KEY',
        client: httpClient,
      );

      final mapper = const FmpStockAnalysisMapper();

      final dataSource = FmpStockMarketDataSource(
        apiClient: apiClient,
        mapper: mapper,
      );

      final result = await dataSource.getStockAnalysisData('AAPL');

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

      expect(
        result.sources,
        ['Financial Modeling Prep'],
      );

      expect(result.dataTimestamp, isNotNull);

      apiClient.dispose();
    },
  );
}