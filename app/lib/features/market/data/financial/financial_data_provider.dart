import 'financial_data.dart';

/// Contrato común para cualquier proveedor de datos financieros.
///
/// ATHENA TYCHE no depende de un proveedor financiero concreto.
/// Cada fuente externa implementará esta interfaz.
abstract interface class FinancialDataProvider {
  /// Identificador único del proveedor.
  String get providerId;

  /// Obtiene los datos financieros de una empresa.
  ///
  /// Devuelve null cuando el proveedor no dispone de información
  /// financiera suficiente para el símbolo solicitado.
  Future<FinancialData?> getFinancialData({
    required String symbol,
  });
}
