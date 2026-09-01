import 'package:http/http.dart' as http;

import '../../analysis/data/datasources/fmp_api_client.dart';

/// Fuente de datos encargada de obtener información agregada
/// del mercado desde Financial Modeling Prep.
///
/// No contiene lógica de inversión ni calcula recomendaciones.
/// Su responsabilidad es únicamente comunicarse con FMP y
/// devolver las respuestas HTTP necesarias para construir
/// el contexto global del mercado.
class FmpMarketContextDataSource {
  final FmpApiClient apiClient;

  const FmpMarketContextDataSource({required this.apiClient});

  /// Obtiene el rendimiento agregado de los sectores.
  Future<http.Response> getSectorPerformance({required String date}) {
    return apiClient.getSectorPerformanceSnapshot(date: date);
  }

  /// Obtiene el rendimiento agregado de las industrias.
  Future<http.Response> getIndustryPerformance({required String date}) {
    return apiClient.getIndustryPerformanceSnapshot(date: date);
  }

  /// Obtiene los mayores ganadores del mercado.
  Future<http.Response> getBiggestGainers() {
    return apiClient.getBiggestGainers();
  }

  /// Obtiene los mayores perdedores del mercado.
  Future<http.Response> getBiggestLosers() {
    return apiClient.getBiggestLosers();
  }

  /// Obtiene los valores con mayor actividad.
  Future<http.Response> getMostActives() {
    return apiClient.getMostActives();
  }
}
