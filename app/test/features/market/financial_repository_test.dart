import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/data/financial/financial_data.dart';
import 'package:app/features/market/data/financial/financial_data_provider.dart';
import 'package:app/features/market/data/financial/financial_repository_impl.dart';

class _FakeFinancialDataProvider implements FinancialDataProvider {
  FinancialData? result;

  @override
  String get providerId => 'fake_financial';

  @override
  Future<FinancialData?> getFinancialData({
    required String symbol,
  }) async {
    return result;
  }
}

void main() {
  test(
    'FinancialRepositoryImpl devuelve los datos proporcionados',
    () async {
      final provider = _FakeFinancialDataProvider();

      provider.result = const FinancialData(
        symbol: 'AAPL',
        providerId: 'test',
        revenue: 1000,
        ebitda: 250,
      );

      final repository = FinancialRepositoryImpl(
        provider: provider,
      );

      final result = await repository.getFinancialData(
        symbol: 'AAPL',
      );

      expect(result, isNotNull);
      expect(result!.symbol, 'AAPL');
      expect(result.revenue, 1000);
      expect(result.ebitda, 250);
      expect(result.providerId, 'test');
    },
  );

  test(
    'FinancialRepositoryImpl devuelve null cuando el proveedor no tiene datos',
    () async {
      final provider = _FakeFinancialDataProvider();

      final repository = FinancialRepositoryImpl(
        provider: provider,
      );

      final result = await repository.getFinancialData(
        symbol: 'AAPL',
      );

      expect(result, isNull);
    },
  );
}
