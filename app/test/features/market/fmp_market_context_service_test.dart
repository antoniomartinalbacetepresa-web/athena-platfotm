import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:app/features/analysis/data/datasources/fmp_api_client.dart';
import 'package:app/features/market/services/fmp_market_context_data_source.dart';
import 'package:app/features/market/services/fmp_market_context_service.dart';

class FakeHttpClient extends http.BaseClient {
  final Map<String, http.Response> responses;

  FakeHttpClient(this.responses);

  @override
  Future<http.StreamedResponse> send(
    http.BaseRequest request,
  ) async {
    final path = request.url.path;

    final response = responses.entries
        .firstWhere(
          (entry) => path.endsWith(entry.key),
          orElse: () => throw StateError(
            'No existe una respuesta simulada para $path',
          ),
        )
        .value;

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

http.Response jsonResponse(String body) {
  return http.Response(
    body,
    200,
    headers: {
      'content-type': 'application/json',
    },
  );
}

void main() {
  test(
    'FmpMarketContextService construye correctamente el contexto',
    () async {
      final httpClient = FakeHttpClient({
        '/stable/sector-performance-snapshot': jsonResponse(
          '''
[
  {
    "sector": "Technology",
    "changesPercentage": 1.2
  },
  {
    "sector": "Healthcare",
    "changesPercentage": -0.4
  },
  {
    "sector": "Financial Services",
    "changesPercentage": 0.8
  }
]
''',
        ),
        '/stable/biggest-gainers': jsonResponse(
          '''
[
  {"symbol": "AAA", "changesPercentage": 8.0},
  {"symbol": "BBB", "changesPercentage": 6.0},
  {"symbol": "CCC", "changesPercentage": 5.0}
]
''',
        ),
        '/stable/biggest-losers': jsonResponse(
          '''
[
  {"symbol": "DDD", "changesPercentage": -7.0},
  {"symbol": "EEE", "changesPercentage": -5.0}
]
''',
        ),
      });

      final apiClient = FmpApiClient(
        apiKey: 'TEST_API_KEY',
        client: httpClient,
      );

      final dataSource = FmpMarketContextDataSource(
        apiClient: apiClient,
      );

      final service = FmpMarketContextService(
        dataSource: dataSource,
      );

      final result = await service.getMarketContext();

      expect(result.assetsAnalyzed, 5);

      expect(
        result.advancingPercentage,
        closeTo(60.0, 0.000001),
      );

      expect(
        result.decliningPercentage,
        closeTo(40.0, 0.000001),
      );

      expect(result.volatility, isNull);
      expect(result.sentiment, 'positive');

      expect(
        result.summary,
        'El mercado presenta un sesgo positivo '
        'según los datos agregados disponibles.',
      );

      expect(result.updatedAt, isNotNull);

      apiClient.dispose();
    },
  );

  test(
    'FmpMarketContextService rechaza un error HTTP de sectores',
    () async {
      final httpClient = FakeHttpClient({
        '/stable/sector-performance-snapshot': http.Response(
          '{"error":"Unauthorized"}',
          401,
        ),
        '/stable/biggest-gainers': jsonResponse('[]'),
        '/stable/biggest-losers': jsonResponse('[]'),
      });

      final apiClient = FmpApiClient(
        apiKey: 'TEST_API_KEY',
        client: httpClient,
      );

      final dataSource = FmpMarketContextDataSource(
        apiClient: apiClient,
      );

      final service = FmpMarketContextService(
        dataSource: dataSource,
      );

      expect(
        () => service.getMarketContext(),
        throwsException,
      );

      apiClient.dispose();
    },
  );

  test(
    'FmpMarketContextService gestiona un mercado sin ganadores ni perdedores',
    () async {
      final httpClient = FakeHttpClient({
        '/stable/sector-performance-snapshot': jsonResponse(
          '''
[
  {
    "sector": "Technology",
    "changesPercentage": 0
  }
]
''',
        ),
        '/stable/biggest-gainers': jsonResponse('[]'),
        '/stable/biggest-losers': jsonResponse('[]'),
      });

      final apiClient = FmpApiClient(
        apiKey: 'TEST_API_KEY',
        client: httpClient,
      );

      final dataSource = FmpMarketContextDataSource(
        apiClient: apiClient,
      );

      final service = FmpMarketContextService(
        dataSource: dataSource,
      );

      final result = await service.getMarketContext();

      expect(result.assetsAnalyzed, 0);
      expect(result.advancingPercentage, 0.0);
      expect(result.decliningPercentage, 0.0);
      expect(result.sentiment, 'neutral');

      apiClient.dispose();
    },
  );

  test(
    'FmpMarketContextService rechaza JSON de sectores con formato incorrecto',
    () async {
      final httpClient = FakeHttpClient({
        '/stable/sector-performance-snapshot': jsonResponse(
          '{"unexpected":"object"}',
        ),
        '/stable/biggest-gainers': jsonResponse('[]'),
        '/stable/biggest-losers': jsonResponse('[]'),
      });

      final apiClient = FmpApiClient(
        apiKey: 'TEST_API_KEY',
        client: httpClient,
      );

      final dataSource = FmpMarketContextDataSource(
        apiClient: apiClient,
      );

      final service = FmpMarketContextService(
        dataSource: dataSource,
      );

      expect(
        () => service.getMarketContext(),
        throwsFormatException,
      );

      apiClient.dispose();
    },
  );

  test(
    'FmpMarketContextService devuelve 100% de avance cuando todos '
    'los activos observados son ganadores',
    () async {
      final httpClient = FakeHttpClient({
        '/stable/sector-performance-snapshot': jsonResponse(
          '''
[
  {
    "sector": "Technology",
    "changesPercentage": 1.0
  }
]
''',
        ),
        '/stable/biggest-gainers': jsonResponse(
          '''
[
  {"symbol": "AAA", "changesPercentage": 8.0},
  {"symbol": "BBB", "changesPercentage": 5.0}
]
''',
        ),
        '/stable/biggest-losers': jsonResponse('[]'),
      });

      final apiClient = FmpApiClient(
        apiKey: 'TEST_API_KEY',
        client: httpClient,
      );

      final service = FmpMarketContextService(
        dataSource: FmpMarketContextDataSource(
          apiClient: apiClient,
        ),
      );

      final result = await service.getMarketContext();

      expect(result.assetsAnalyzed, 2);
      expect(result.advancingPercentage, 100.0);
      expect(result.decliningPercentage, 0.0);
      expect(result.sentiment, 'positive');

      apiClient.dispose();
    },
  );

  test(
    'FmpMarketContextService devuelve 100% de descenso cuando todos '
    'los activos observados son perdedores',
    () async {
      final httpClient = FakeHttpClient({
        '/stable/sector-performance-snapshot': jsonResponse(
          '''
[
  {
    "sector": "Technology",
    "changesPercentage": -1.0
  }
]
''',
        ),
        '/stable/biggest-gainers': jsonResponse('[]'),
        '/stable/biggest-losers': jsonResponse(
          '''
[
  {"symbol": "AAA", "changesPercentage": -8.0},
  {"symbol": "BBB", "changesPercentage": -5.0}
]
''',
        ),
      });

      final apiClient = FmpApiClient(
        apiKey: 'TEST_API_KEY',
        client: httpClient,
      );

      final service = FmpMarketContextService(
        dataSource: FmpMarketContextDataSource(
          apiClient: apiClient,
        ),
      );

      final result = await service.getMarketContext();

      expect(result.assetsAnalyzed, 2);
      expect(result.advancingPercentage, 0.0);
      expect(result.decliningPercentage, 100.0);
      expect(result.sentiment, 'negative');

      apiClient.dispose();
    },
  );

  test(
    'FmpMarketContextService utiliza la amplitud cuando los sectores están empatados',
    () async {
      final httpClient = FakeHttpClient({
        '/stable/sector-performance-snapshot': jsonResponse(
          '''
[
  {
    "sector": "Technology",
    "changesPercentage": 1.0
  },
  {
    "sector": "Healthcare",
    "changesPercentage": -1.0
  }
]
''',
        ),
        '/stable/biggest-gainers': jsonResponse(
          '''
[
  {"symbol": "AAA", "changesPercentage": 8.0},
  {"symbol": "BBB", "changesPercentage": 5.0},
  {"symbol": "CCC", "changesPercentage": 4.0}
]
''',
        ),
        '/stable/biggest-losers': jsonResponse(
          '''
[
  {"symbol": "DDD", "changesPercentage": -3.0}
]
''',
        ),
      });

      final apiClient = FmpApiClient(
        apiKey: 'TEST_API_KEY',
        client: httpClient,
      );

      final service = FmpMarketContextService(
        dataSource: FmpMarketContextDataSource(
          apiClient: apiClient,
        ),
      );

      final result = await service.getMarketContext();

      expect(result.assetsAnalyzed, 4);
      expect(result.advancingPercentage, 75.0);
      expect(result.decliningPercentage, 25.0);
      expect(result.sentiment, 'positive');

      apiClient.dispose();
    },
  );

  test(
    'FmpMarketContextService acepta cambios sectoriales enviados como texto',
    () async {
      final httpClient = FakeHttpClient({
        '/stable/sector-performance-snapshot': jsonResponse(
          '''
[
  {
    "sector": "Technology",
    "changesPercentage": "2.5%"
  },
  {
    "sector": "Healthcare",
    "changesPercentage": "-1.0%"
  },
  {
    "sector": "Energy"
  }
]
''',
        ),
        '/stable/biggest-gainers': jsonResponse(
          '''
[
  {"symbol": "AAA", "changesPercentage": 4.0}
]
''',
        ),
        '/stable/biggest-losers': jsonResponse(
          '''
[
  {"symbol": "BBB", "changesPercentage": -2.0}
]
''',
        ),
      });

      final apiClient = FmpApiClient(
        apiKey: 'TEST_API_KEY',
        client: httpClient,
      );

      final service = FmpMarketContextService(
        dataSource: FmpMarketContextDataSource(
          apiClient: apiClient,
        ),
      );

      final result = await service.getMarketContext();

      expect(result.assetsAnalyzed, 2);
      expect(result.advancingPercentage, 50.0);
      expect(result.decliningPercentage, 50.0);
      expect(result.sentiment, 'neutral');

      apiClient.dispose();
    },
  );
}