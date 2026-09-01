import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/analysis/data/datasources/fmp_api_client.dart';
import 'package:app/features/market/services/fmp_market_universe_data_source.dart';

void main() {
  group('FmpMarketUniverseDataSource', () {
    test(
      'obtiene una página del universo y transforma correctamente los activos',
      () async {
        final client = MockClient((request) async {
          expect(request.method, 'GET');
          expect(request.url.path, '/stable/company-screener');
          expect(request.url.queryParameters['page'], '0');
          expect(request.url.queryParameters['limit'], '1000');
          expect(
            request.url.queryParameters['isActivelyTrading'],
            'true',
          );
          expect(
            request.url.queryParameters['apikey'],
            'test-key',
          );

          return http.Response(
            jsonEncode([
              {
                'symbol': 'AAPL',
                'companyName': 'Apple Inc.',
                'marketCap': 3000000000000,
                'country': 'United States',
                'exchange': 'NASDAQ Global Select Market',
                'exchangeShortName': 'NMS',
                'sector': 'Technology',
                'industry': 'Consumer Electronics',
              },
            ]),
            200,
          );
        });

        final apiClient = FmpApiClient(
          apiKey: 'test-key',
          client: client,
        );

        final dataSource = FmpMarketUniverseDataSource(
          apiClient: apiClient,
        );

        final assets = await dataSource.getUniverse();

        expect(assets, hasLength(1));

        final asset = assets.single;

        expect(asset.symbol, 'AAPL');
        expect(asset.companyName, 'Apple Inc.');
        expect(asset.marketCap, 3000000000000);
        expect(asset.country, 'United States');
        expect(
          asset.exchange,
          'NASDAQ Global Select Market',
        );
        expect(asset.exchangeShortName, 'NMS');
        expect(asset.sector, 'Technology');
        expect(
          asset.industry,
          'Consumer Electronics',
        );
        expect(asset.listingKey, 'AAPL@NMS');

        apiClient.dispose();
      },
    );

    test(
      'recorre páginas cuando una página está llena y termina con una página menor',
      () async {
        final requestedPages = <String>[];

        final client = MockClient((request) async {
          final page = request.url.queryParameters['page'];

          requestedPages.add(page!);

          if (page == '0') {
            return http.Response(
              jsonEncode(
                List.generate(
                  1000,
                  (index) => {
                    'symbol': 'SYM$index',
                    'companyName': 'Company $index',
                    'marketCap': 1000 + index,
                    'country': 'United States',
                  },
                ),
              ),
              200,
            );
          }

          if (page == '1') {
            return http.Response(
              jsonEncode([
                {
                  'symbol': 'LAST',
                  'companyName': 'Last Company',
                  'marketCap': 5000,
                  'country': 'Spain',
                },
              ]),
              200,
            );
          }

          fail('No debería solicitarse la página $page');
        });

        final apiClient = FmpApiClient(
          apiKey: 'test-key',
          client: client,
        );

        final dataSource = FmpMarketUniverseDataSource(
          apiClient: apiClient,
        );

        final assets = await dataSource.getUniverse();

        expect(requestedPages, ['0', '1']);
        expect(assets, hasLength(1001));
        expect(assets.last.symbol, 'LAST');

        apiClient.dispose();
      },
    );

    test(
      'elimina duplicados del mismo listado utilizando listingKey',
      () async {
        final client = MockClient((request) async {
          return http.Response(
            jsonEncode([
              {
                'symbol': 'AAPL',
                'companyName': 'Apple Inc.',
                'marketCap': 100,
                'country': 'United States',
                'exchange': 'NASDAQ',
                'exchangeShortName': 'NMS',
              },
              {
                'symbol': 'AAPL',
                'companyName': 'Apple Inc. Updated',
                'marketCap': 200,
                'country': 'United States',
                'exchange': 'NASDAQ',
                'exchangeShortName': 'NMS',
              },
            ]),
            200,
          );
        });

        final apiClient = FmpApiClient(
          apiKey: 'test-key',
          client: client,
        );

        final dataSource = FmpMarketUniverseDataSource(
          apiClient: apiClient,
        );

        final assets = await dataSource.getUniverse();

        expect(assets, hasLength(1));
        expect(assets.single.symbol, 'AAPL');
        expect(
          assets.single.companyName,
          'Apple Inc. Updated',
        );
        expect(assets.single.marketCap, 200);
        expect(assets.single.listingKey, 'AAPL@NMS');

        apiClient.dispose();
      },
    );

    test(
      'conserva listados diferentes aunque compartan el mismo símbolo',
      () async {
        final client = MockClient((request) async {
          return http.Response(
            jsonEncode([
              {
                'symbol': 'AAPL',
                'companyName': 'Apple Inc.',
                'marketCap': 100,
                'country': 'United States',
                'exchange': 'NASDAQ',
                'exchangeShortName': 'NMS',
              },
              {
                'symbol': 'AAPL',
                'companyName': 'Apple Inc.',
                'marketCap': 110,
                'country': 'United States',
                'exchange': 'New York Stock Exchange',
                'exchangeShortName': 'NYQ',
              },
            ]),
            200,
          );
        });

        final apiClient = FmpApiClient(
          apiKey: 'test-key',
          client: client,
        );

        final dataSource = FmpMarketUniverseDataSource(
          apiClient: apiClient,
        );

        final assets = await dataSource.getUniverse();

        expect(assets, hasLength(2));

        expect(
          assets.map((asset) => asset.listingKey),
          containsAll([
            'AAPL@NMS',
            'AAPL@NYQ',
          ]),
        );

        apiClient.dispose();
      },
    );

    test(
      'deduplica símbolos cuando no existe información de exchange',
      () async {
        final client = MockClient((request) async {
          return http.Response(
            jsonEncode([
              {
                'symbol': 'AAPL',
                'companyName': 'Apple Inc.',
                'marketCap': 100,
                'country': 'United States',
              },
              {
                'symbol': 'AAPL',
                'companyName': 'Apple Inc. Updated',
                'marketCap': 200,
                'country': 'United States',
              },
            ]),
            200,
          );
        });

        final apiClient = FmpApiClient(
          apiKey: 'test-key',
          client: client,
        );

        final dataSource = FmpMarketUniverseDataSource(
          apiClient: apiClient,
        );

        final assets = await dataSource.getUniverse();

        expect(assets, hasLength(1));
        expect(assets.single.symbol, 'AAPL');
        expect(
          assets.single.companyName,
          'Apple Inc. Updated',
        );
        expect(assets.single.marketCap, 200);
        expect(assets.single.listingKey, 'AAPL');

        apiClient.dispose();
      },
    );

    test(
      'ignora activos que no tienen símbolo o nombre de compañía válidos',
      () async {
        final client = MockClient((request) async {
          return http.Response(
            jsonEncode([
              {
                'symbol': 'VALID',
                'companyName': 'Valid Company',
                'marketCap': 100,
                'country': 'United States',
              },
              {
                'symbol': '',
                'companyName': 'Invalid Symbol',
                'marketCap': 100,
                'country': 'United States',
              },
              {
                'symbol': 'NO_NAME',
                'companyName': '',
                'marketCap': 100,
                'country': 'Spain',
              },
              {
                'companyName': 'Missing Symbol',
                'marketCap': 100,
                'country': 'Japan',
              },
              {
                'symbol': 'MISSING_NAME',
                'marketCap': 100,
                'country': 'Japan',
              },
            ]),
            200,
          );
        });

        final apiClient = FmpApiClient(
          apiKey: 'test-key',
          client: client,
        );

        final dataSource = FmpMarketUniverseDataSource(
          apiClient: apiClient,
        );

        final assets = await dataSource.getUniverse();

        expect(assets, hasLength(1));
        expect(assets.single.symbol, 'VALID');

        apiClient.dispose();
      },
    );

    test(
      'convierte correctamente marketCap cuando FMP devuelve un texto numérico',
      () async {
        final client = MockClient((request) async {
          return http.Response(
            jsonEncode([
              {
                'symbol': 'TEST',
                'companyName': 'Test Company',
                'marketCap': '123456.78',
                'country': 'Spain',
              },
            ]),
            200,
          );
        });

        final apiClient = FmpApiClient(
          apiKey: 'test-key',
          client: client,
        );

        final dataSource = FmpMarketUniverseDataSource(
          apiClient: apiClient,
        );

        final assets = await dataSource.getUniverse();

        expect(assets, hasLength(1));
        expect(assets.single.marketCap, 123456.78);

        apiClient.dispose();
      },
    );

    test(
      'acepta marketCap nulo sin descartar el activo',
      () async {
        final client = MockClient((request) async {
          return http.Response(
            jsonEncode([
              {
                'symbol': 'NOCAP',
                'companyName': 'No Cap Company',
                'marketCap': null,
                'country': 'Japan',
              },
            ]),
            200,
          );
        });

        final apiClient = FmpApiClient(
          apiKey: 'test-key',
          client: client,
        );

        final dataSource = FmpMarketUniverseDataSource(
          apiClient: apiClient,
        );

        final assets = await dataSource.getUniverse();

        expect(assets, hasLength(1));
        expect(assets.single.symbol, 'NOCAP');
        expect(assets.single.marketCap, isNull);

        apiClient.dispose();
      },
    );

    test(
      'lanza una excepción cuando FMP responde con un código HTTP distinto de 200',
      () async {
        final client = MockClient((request) async {
          return http.Response(
            '{"error":"Unauthorized"}',
            401,
          );
        });

        final apiClient = FmpApiClient(
          apiKey: 'test-key',
          client: client,
        );

        final dataSource = FmpMarketUniverseDataSource(
          apiClient: apiClient,
        );

        expect(
          dataSource.getUniverse,
          throwsException,
        );

        apiClient.dispose();
      },
    );

    test(
      'lanza una excepción cuando FMP devuelve un formato JSON inesperado',
      () async {
        final client = MockClient((request) async {
          return http.Response(
            jsonEncode({
              'error': 'unexpected format',
            }),
            200,
          );
        });

        final apiClient = FmpApiClient(
          apiKey: 'test-key',
          client: client,
        );

        final dataSource = FmpMarketUniverseDataSource(
          apiClient: apiClient,
        );

        expect(
          dataSource.getUniverse,
          throwsException,
        );

        apiClient.dispose();
      },
    );

    test(
      'termina correctamente cuando FMP devuelve una página vacía',
      () async {
        var calls = 0;

        final client = MockClient((request) async {
          calls++;

          return http.Response(
            jsonEncode([]),
            200,
          );
        });

        final apiClient = FmpApiClient(
          apiKey: 'test-key',
          client: client,
        );

        final dataSource = FmpMarketUniverseDataSource(
          apiClient: apiClient,
        );

        final assets = await dataSource.getUniverse();

        expect(calls, 1);
        expect(assets, isEmpty);

        apiClient.dispose();
      },
    );
  });
}