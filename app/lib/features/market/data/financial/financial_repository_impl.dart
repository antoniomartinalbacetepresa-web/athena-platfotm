import 'financial_data.dart';
import 'financial_data_provider.dart';
import 'financial_repository.dart';

/// Implementación del repositorio financiero.
///
/// Delega la obtención de datos al proveedor financiero configurado.
/// El resto de ATHENA TYCHE queda desacoplado del proveedor concreto.
class FinancialRepositoryImpl implements FinancialRepository {
  final FinancialDataProvider provider;

  const FinancialRepositoryImpl({
    required this.provider,
  });

  @override
  Future<FinancialData?> getFinancialData({
    required String symbol,
  }) {
    return provider.getFinancialData(
      symbol: symbol,
    );
  }
}
