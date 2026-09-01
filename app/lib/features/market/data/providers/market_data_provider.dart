import '../models/market_data_point.dart';

/// Contrato común para cualquier proveedor de datos de mercado.
///
/// ATHENA TYCHE no debe depender de un proveedor concreto.
/// Cada proveedor externo implementará esta interfaz.
abstract interface class MarketDataProvider {
  /// Identificador único del proveedor.
  String get providerId;

  /// Obtiene la cotización actual de un símbolo.
  ///
  /// Devuelve null cuando el proveedor no dispone de una
  /// cotización válida.
  Future<MarketDataPoint?> getQuote(String symbol);

  /// Obtiene datos históricos de un símbolo.
  ///
  /// [from] y [to] permiten limitar el periodo solicitado.
  Future<List<MarketDataPoint>> getHistoricalData({
    required String symbol,
    DateTime? from,
    DateTime? to,
  });
}