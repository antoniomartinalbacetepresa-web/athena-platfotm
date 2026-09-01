import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:app/features/analysis/data/datasources/fmp_api_client.dart';
import 'package:app/features/analysis/data/datasources/fmp_stock_market_data_source.dart';
import 'package:app/features/market/services/fmp_market_service.dart';

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
    'FmpMarketService transforma correctamente una respuesta de FMP',
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

      final dataSource = FmpStockMarketDataSource(
        apiClient: apiClient,
      );

      final service = FmpMarketService(
        dataSource: dataSource,
      );

      final result = await service.getQuote('aapl');

      expect(result.symbol, 'AAPL');
      expect(result.companyName, 'Apple Inc.');

      expect(result.currentPrice, 305.93);

      expect(
        result.change,
        closeTo(0.67, 0.000001),
      );

      expect(
        result.changePercentage,
        0.21949,
      );

      expect(
        result.updatedAt,
        DateTime.fromMillisecondsSinceEpoch(
          1786737601 * 1000,
          isUtc: true,
        ),
      );

      apiClient.dispose();
    },
  );

  test(
    'FmpMarketService rechaza un símbolo vacío',
    () async {
      final fakeResponse = http.Response(
        '[]',
        200,
      );

      final httpClient = FakeHttpClient(fakeResponse);

      final apiClient = FmpApiClient(
        apiKey: 'TEST_API_KEY',
        client: httpClient,
      );

      final dataSource = FmpStockMarketDataSource(
        apiClient: apiClient,
      );

      final service = FmpMarketService(
        dataSource: dataSource,
      );

      expect(
        () => service.getQuote('   '),
        throwsArgumentError,
      );

      apiClient.dispose();
    },
  );

  test(
    'FmpMarketService rechaza una respuesta HTTP incorrecta',
    () async {
      final fakeResponse = http.Response(
        '{"error":"Unauthorized"}',
        401,
      );

      final httpClient = FakeHttpClient(fakeResponse);

      final apiClient = FmpApiClient(
        apiKey: 'TEST_API_KEY',
        client: httpClient,
      );

      final dataSource = FmpStockMarketDataSource(
        apiClient: apiClient,
      );

      final service = FmpMarketService(
        dataSource: dataSource,
      );

      expect(
        () => service.getQuote('AAPL'),
        throwsException,
      );

      apiClient.dispose();
    },
  );

  test(
    'FmpMarketService rechaza una respuesta sin datos',
    () async {
      final fakeResponse = http.Response(
        '[]',
        200,
      );

      final httpClient = FakeHttpClient(fakeResponse);

      final apiClient = FmpApiClient(
        apiKey: 'TEST_API_KEY',
        client: httpClient,
      );

      final dataSource = FmpStockMarketDataSource(
        apiClient: apiClient,
      );

      final service = FmpMarketService(
        dataSource: dataSource,
      );

      expect(
        () => service.getQuote('AAPL'),
        throwsException,
      );

      apiClient.dispose();
    },
  );
}