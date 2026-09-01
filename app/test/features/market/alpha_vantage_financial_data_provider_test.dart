import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/market/data/financial/alpha_vantage_financial_data_provider.dart';

void main() {
  group('AlphaVantageFinancialDataProvider', () {
    test('devuelve null cuando el símbolo está vacío', () async {
      final provider = AlphaVantageFinancialDataProvider(
        apiKey: 'test-key',
        client: MockClient((_) async {
          fail('No debería realizar ninguna petición HTTP.');
        }),
      );

      final result = await provider.getFinancialData(symbol: '   ');

      expect(result, isNull);
    });

    test('devuelve null cuando la API key está vacía', () async {
      final provider = AlphaVantageFinancialDataProvider(
        apiKey: '',
        client: MockClient((_) async {
          fail('No debería realizar ninguna petición HTTP.');
        }),
      );

      final result = await provider.getFinancialData(symbol: 'AAPL');

      expect(result, isNull);
    });

    test('normaliza el símbolo y obtiene datos financieros', () async {
      var requestCount = 0;

      final provider = AlphaVantageFinancialDataProvider(
        apiKey: 'test-key',
        client: MockClient((request) async {
          requestCount++;

          final function = request.url.queryParameters['function'];

          if (function == 'OVERVIEW') {
            return http.Response(
              jsonEncode({
                'Name': 'Apple Inc.',
                'Currency': 'USD',
                'EPS': '7.25',
                'ProfitMargin': '0.22',
                'OperatingMarginTTM': '0.28',
                'EBITDA': '130000000000',
              }),
              200,
            );
          }

          if (function == 'INCOME_STATEMENT') {
            return http.Response(
              jsonEncode({
                'annualReports': [
                  {
                    'fiscalDateEnding': '2025-12-31',
                    'totalRevenue': '500000000000',
                    'ebitda': '130000000000',
                    'ebit': '120000000000',
                    'netIncome': '100000000000',
                  },
                ],
              }),
              200,
            );
          }

          if (function == 'BALANCE_SHEET') {
            return http.Response(
              jsonEncode({
                'annualReports': [
                  {
                    'cashAndCashEquivalentsAtCarryingValue':
                        '50000000000',
                    'shortLongTermDebtTotal': '100000000000',
                  },
                ],
              }),
              200,
            );
          }

          if (function == 'CASH_FLOW') {
            return http.Response(
              jsonEncode({
                'annualReports': [
                  {
                    'operatingCashflow': '120000000000',
                    'capitalExpenditures': '10000000000',
                  },
                ],
              }),
              200,
            );
          }

          return http.Response('{}', 200);
        }),
      );

      final result =
          await provider.getFinancialData(symbol: ' aapl ');

      expect(result, isNotNull);
      expect(result!.symbol, 'AAPL');
      expect(result.companyName, 'Apple Inc.');
      expect(result.currency, 'USD');
      expect(result.periodType, 'annual');

      expect(result.revenue, 500000000000);
      expect(result.ebitda, 130000000000);
      expect(result.ebit, 120000000000);
      expect(result.netIncome, 100000000000);
      expect(result.eps, 7.25);

      expect(result.cash, 50000000000);
      expect(result.totalDebt, 100000000000);

      expect(result.grossMargin, 0.22);
      expect(result.operatingMargin, 0.28);
      expect(result.netMargin, 0.22);

      expect(result.operatingCashFlow, 120000000000);
      expect(result.freeCashFlow, 110000000000);

      expect(
        result.periodEnd,
        DateTime(2025, 12, 31),
      );

      expect(result.providerId, 'alpha_vantage');
      expect(requestCount, 4);
    });

    test('utiliza EBITDA del overview si income statement no lo proporciona',
        () async {
      final provider = AlphaVantageFinancialDataProvider(
        apiKey: 'test-key',
        client: MockClient((request) async {
          final function = request.url.queryParameters['function'];

          if (function == 'OVERVIEW') {
            return http.Response(
              jsonEncode({
                'Name': 'Test Company',
                'Currency': 'USD',
                'EBITDA': '9000',
              }),
              200,
            );
          }

          if (function == 'INCOME_STATEMENT') {
            return http.Response(
              jsonEncode({
                'annualReports': [
                  {
                    'fiscalDateEnding': '2025-12-31',
                    'totalRevenue': '20000',
                    'ebit': '5000',
                    'netIncome': '4000',
                  },
                ],
              }),
              200,
            );
          }

          if (function == 'BALANCE_SHEET') {
            return http.Response(
              jsonEncode({
                'annualReports': [{}],
              }),
              200,
            );
          }

          if (function == 'CASH_FLOW') {
            return http.Response(
              jsonEncode({
                'annualReports': [{}],
              }),
              200,
            );
          }

          return http.Response('{}', 200);
        }),
      );

      final result =
          await provider.getFinancialData(symbol: 'TEST');

      expect(result, isNotNull);
      expect(result!.ebitda, 9000);
    });

    test('lanza excepción ante un error HTTP', () async {
      final provider = AlphaVantageFinancialDataProvider(
        apiKey: 'test-key',
        client: MockClient((_) async {
          return http.Response('Server error', 500);
        }),
      );

      expect(
        () => provider.getFinancialData(symbol: 'AAPL'),
        throwsException,
      );
    });

    test('lanza excepción cuando Alpha Vantage devuelve Error Message',
        () async {
      final provider = AlphaVantageFinancialDataProvider(
        apiKey: 'test-key',
        client: MockClient((_) async {
          return http.Response(
            jsonEncode({
              'Error Message': 'Invalid API call.',
            }),
            200,
          );
        }),
      );

      expect(
        () => provider.getFinancialData(symbol: 'AAPL'),
        throwsException,
      );
    });

    test('lanza excepción cuando Alpha Vantage devuelve Information',
        () async {
      final provider = AlphaVantageFinancialDataProvider(
        apiKey: 'test-key',
        client: MockClient((_) async {
          return http.Response(
            jsonEncode({
              'Information': 'Rate limit reached.',
            }),
            200,
          );
        }),
      );

      expect(
        () => provider.getFinancialData(symbol: 'AAPL'),
        throwsException,
      );
    });

    test('devuelve null cuando OVERVIEW está vacío', () async {
      final provider = AlphaVantageFinancialDataProvider(
        apiKey: 'test-key',
        client: MockClient((request) async {
          return http.Response('{}', 200);
        }),
      );

      final result =
          await provider.getFinancialData(symbol: 'AAPL');

      expect(result, isNull);
    });

    test('identifica correctamente el proveedor', () {
      final provider = AlphaVantageFinancialDataProvider(
        apiKey: 'test-key',
      );

      expect(provider.providerId, 'alpha_vantage');
    });
  });
}
