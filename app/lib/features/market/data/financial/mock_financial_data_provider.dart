import 'financial_data.dart';
import 'financial_data_provider.dart';

/// Proveedor financiero local utilizado para desarrollo y pruebas.
///
/// No realiza conexiones externas ni representa datos reales de mercado.
class MockFinancialDataProvider implements FinancialDataProvider {
  static const String _providerId = 'mock_financial';

  const MockFinancialDataProvider();

  @override
  String get providerId => _providerId;

  @override
  Future<FinancialData?> getFinancialData({
    required String symbol,
  }) async {
    final normalizedSymbol = symbol.trim().toUpperCase();

    if (normalizedSymbol.isEmpty) {
      return null;
    }

    return FinancialData(
      symbol: normalizedSymbol,
      companyName: 'Mock Company',
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
      providerId: providerId,
    );
  }
}
