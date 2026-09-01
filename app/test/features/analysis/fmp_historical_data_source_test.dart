import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:app/features/analysis/data/datasources/fmp_api_client.dart';
import 'package:app/features/analysis/data/datasources/fmp_historical_data_source.dart';

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
    'FmpHistoricalDataSource transforma correctamente el histórico de FMP',
    () async {
      final fakeResponse = http.Response(
        '''
        {
          "historical": [
            {
              "date": "2026-01-05",
              "open": 245.00,
              "high": 250.00,
              "low": 242.00,
              "close": 248.00,
              "adjClose": 248.00,
              "volume": 45000000
            },
            {
              "date": "2026-01-03",
              "open": 240.00,
              "high": 244.00,
              "low": 238.00,
              "close": 242.00,
              "adjClose": 242.00,
              "volume": 42000000
            },
            {
              "date": "2026-01-04",
              "open": 242.00,
              "high": 247.00,
              "low": 241.00,
              "close": 245.00,
              "adjClose": 245.00,
              "volume": 43000000
            }
          ]
        }
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

      final dataSource = FmpHistoricalDataSource(
        apiClient: apiClient,
      );

      final result = await dataSource.getHistoricalPrices('aapl');

      expect(result.length, 3);

      // Debe quedar ordenado de más antiguo a más reciente.
      expect(
        result[0].date,
        DateTime(2026, 1, 3),
      );

      expect(
        result[1].date,
        DateTime(2026, 1, 4),
      );

      expect(
        result[2].date,
        DateTime(2026, 1, 5),
      );

      // Primera observación.
      expect(result[0].open, 240.00);
      expect(result[0].high, 244.00);
      expect(result[0].low, 238.00);
      expect(result[0].close, 242.00);
      expect(result[0].adjustedClose, 242.00);
      expect(result[0].volume, 42000000);

      // Última observación.
      expect(result[2].open, 245.00);
      expect(result[2].high, 250.00);
      expect(result[2].low, 242.00);
      expect(result[2].close, 248.00);
      expect(result[2].adjustedClose, 248.00);
      expect(result[2].volume, 45000000);

      apiClient.dispose();
    },
  );

  test(
    'FmpHistoricalDataSource rechaza un símbolo vacío',
    () async {
      final fakeResponse = http.Response(
        '{"historical":[]}',
        200,
      );

      final httpClient = FakeHttpClient(fakeResponse);

      final apiClient = FmpApiClient(
        apiKey: 'TEST_API_KEY',
        client: httpClient,
      );

      final dataSource = FmpHistoricalDataSource(
        apiClient: apiClient,
      );

      expect(
        () => dataSource.getHistoricalPrices('   '),
        throwsArgumentError,
      );

      apiClient.dispose();
    },
  );

  test(
    'FmpHistoricalDataSource devuelve lista vacía cuando no hay histórico',
    () async {
      final fakeResponse = http.Response(
        '''
        {
          "historical": []
        }
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

      final dataSource = FmpHistoricalDataSource(
        apiClient: apiClient,
      );

      final result = await dataSource.getHistoricalPrices('AAPL');

      expect(result, isEmpty);

      apiClient.dispose();
    },
  );
}