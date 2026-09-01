import 'package:http/http.dart' as http;

/// Cliente HTTP encargado exclusivamente de comunicarse con FMP.
///
/// Responsabilidades:
/// - construir las peticiones a la API actual de FMP;
/// - enviar la API key;
/// - devolver las respuestas HTTP.
///
/// No contiene:
/// - lógica de análisis,
/// - reglas de inversión,
/// - cálculos de puntuación,
/// - transformación a modelos de dominio.
class FmpApiClient {
  final String apiKey;
  final http.Client client;

  FmpApiClient({
    required this.apiKey,
    http.Client? client,
  }) : client = client ?? http.Client();

  /// Obtiene la cotización actual de una acción o índice.
  Future<http.Response> getQuote(String symbol) {
    final uri = Uri.https(
      'financialmodelingprep.com',
      '/stable/quote',
      {
        'symbol': symbol,
        'apikey': apiKey,
      },
    );

    return client.get(uri);
  }

  /// Obtiene los datos históricos diarios de una acción.
  ///
  /// FMP devuelve las observaciones dentro de la propiedad
  /// `historical`.
  Future<http.Response> getHistoricalPrices(String symbol) {
    final uri = Uri.https(
      'financialmodelingprep.com',
      '/stable/historical-price-eod/full',
      {
        'symbol': symbol,
        'apikey': apiKey,
      },
    );

    return client.get(uri);
  }

  /// Obtiene una página del universo de compañías de FMP.
  ///
  /// Utiliza el endpoint estable `company-screener`.
  ///
  /// [page] comienza en 0.
  /// [limit] representa únicamente el tamaño de la página,
  /// no el número máximo de activos que tendrá ATHENA TYCHE.
  Future<http.Response> getCompanyScreenerPage({
    int page = 0,
    int limit = 1000,
  }) {
    if (page < 0) {
      throw ArgumentError.value(
        page,
        'page',
        'La página no puede ser negativa.',
      );
    }

    if (limit <= 0) {
      throw ArgumentError.value(
        limit,
        'limit',
        'El límite debe ser mayor que cero.',
      );
    }

    final uri = Uri.https(
      'financialmodelingprep.com',
      '/stable/company-screener',
      {
        'page': page.toString(),
        'limit': limit.toString(),
        'isActivelyTrading': 'true',
        'apikey': apiKey,
      },
    );

    return client.get(uri);
  }

  /// Obtiene el rendimiento agregado de los sectores del mercado.
  ///
  /// La fecha debe utilizar el formato YYYY-MM-DD.
  Future<http.Response> getSectorPerformanceSnapshot({
    required String date,
  }) {
    final uri = Uri.https(
      'financialmodelingprep.com',
      '/stable/sector-performance-snapshot',
      {
        'date': date,
        'apikey': apiKey,
      },
    );

    return client.get(uri);
  }

  /// Obtiene el rendimiento agregado de las industrias del mercado.
  ///
  /// La fecha debe utilizar el formato YYYY-MM-DD.
  Future<http.Response> getIndustryPerformanceSnapshot({
    required String date,
  }) {
    final uri = Uri.https(
      'financialmodelingprep.com',
      '/stable/industry-performance-snapshot',
      {
        'date': date,
        'apikey': apiKey,
      },
    );

    return client.get(uri);
  }

  /// Obtiene las acciones con mayores subidas del mercado.
  Future<http.Response> getBiggestGainers() {
    final uri = Uri.https(
      'financialmodelingprep.com',
      '/stable/biggest-gainers',
      {
        'apikey': apiKey,
      },
    );

    return client.get(uri);
  }

  /// Obtiene las acciones con mayores bajadas del mercado.
  Future<http.Response> getBiggestLosers() {
    final uri = Uri.https(
      'financialmodelingprep.com',
      '/stable/biggest-losers',
      {
        'apikey': apiKey,
      },
    );

    return client.get(uri);
  }

  /// Obtiene las acciones con mayor actividad negociadora.
  Future<http.Response> getMostActives() {
    final uri = Uri.https(
      'financialmodelingprep.com',
      '/stable/most-actives',
      {
        'apikey': apiKey,
      },
    );

    return client.get(uri);
  }

  /// Libera el cliente HTTP.
  void dispose() {
    client.close();
  }
}