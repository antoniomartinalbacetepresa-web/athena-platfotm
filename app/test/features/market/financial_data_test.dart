import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/data/financial/financial_data.dart';

void main() {
  group('FinancialData', () {
    test('crea correctamente datos financieros con EBITDA', () {
      final data = FinancialData(
        symbol: 'AAPL',
        companyName: 'Apple Inc.',
        currency: 'USD',
        periodEnd: DateTime(2025, 12, 31),
        periodType: 'annual',
        revenue: 100000.0,
        ebitda: 30000.0,
        ebit: 28000.0,
        netIncome: 22000.0,
        eps: 7.25,
        cash: 50000.0,
        totalDebt: 100000.0,
        grossMargin: 0.46,
        operatingMargin: 0.28,
        netMargin: 0.22,
        operatingCashFlow: 35000.0,
        freeCashFlow: 30000.0,
        providerId: 'test_provider',
      );

      expect(data.symbol, 'AAPL');
      expect(data.companyName, 'Apple Inc.');
      expect(data.currency, 'USD');
      expect(data.periodType, 'annual');
      expect(data.revenue, 100000.0);
      expect(data.ebitda, 30000.0);
      expect(data.ebit, 28000.0);
      expect(data.netIncome, 22000.0);
      expect(data.eps, 7.25);
      expect(data.cash, 50000.0);
      expect(data.totalDebt, 100000.0);
      expect(data.grossMargin, 0.46);
      expect(data.operatingMargin, 0.28);
      expect(data.netMargin, 0.22);
      expect(data.operatingCashFlow, 35000.0);
      expect(data.freeCashFlow, 30000.0);
      expect(data.providerId, 'test_provider');
    });

    test('permite EBITDA desconocido sin inventar un valor', () {
      const data = FinancialData(
        symbol: 'TEST',
        providerId: 'test_provider',
      );

      expect(data.ebitda, isNull);
      expect(data.revenue, isNull);
      expect(data.ebit, isNull);
      expect(data.netIncome, isNull);
      expect(data.eps, isNull);
      expect(data.cash, isNull);
      expect(data.totalDebt, isNull);
    });

    test('mantiene la identificación del proveedor', () {
      const data = FinancialData(
        symbol: 'MSFT',
        providerId: 'example_provider',
      );

      expect(data.providerId, 'example_provider');
    });
  });
}
