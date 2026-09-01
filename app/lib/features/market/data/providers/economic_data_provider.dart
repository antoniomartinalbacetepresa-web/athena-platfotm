import '../models/economic_data_point.dart';

/// Contrato para proveedores de información macroeconómica.
abstract interface class EconomicDataProvider {
  /// Identificador único del proveedor.
  String get providerId;

  /// Obtiene un indicador económico.
  Future<List<EconomicDataPoint>> getSeries(String seriesId);
}