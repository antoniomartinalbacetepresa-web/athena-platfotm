import '../models/fundamental_data.dart';

/// Contrato común para proveedores de información fundamental.
///
/// Permite combinar fuentes oficiales y fuentes secundarias
/// sin acoplar el dominio de ATHENA TYCHE a un proveedor concreto.
abstract interface class FundamentalDataProvider {
  /// Identificador único del proveedor.
  String get providerId;

  /// Obtiene los fundamentales de una empresa.
  Future<FundamentalData?> getFundamentals(String symbol);
}