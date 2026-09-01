import 'financial_data.dart';

/// Contrato de acceso a los datos financieros de ATHENA TYCHE.
///
/// El resto de la aplicación utiliza este contrato y no depende
/// directamente de proveedores externos.
abstract interface class FinancialRepository {
  /// Obtiene los datos financieros de un símbolo.
  Future<FinancialData?> getFinancialData({
    required String symbol,
  });
}
