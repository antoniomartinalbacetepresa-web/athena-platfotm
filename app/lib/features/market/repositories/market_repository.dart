import '../models/market_quote.dart';

/// Repositorio de datos de mercado utilizados por ATHENA TYCHE.
abstract interface class MarketRepository {
  /// Obtiene la cotización actual de un símbolo.
  Future<MarketQuote> getQuote(String symbol);
}
