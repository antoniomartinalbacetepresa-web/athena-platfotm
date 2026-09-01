import '../models/market_quote.dart';
import 'market_service.dart';

class MockMarketService implements MarketService {
  const MockMarketService();

  @override
  Future<MarketQuote> getQuote(String symbol) async {
    final normalizedSymbol = symbol.trim().toUpperCase();

    if (normalizedSymbol.isEmpty) {
      throw ArgumentError(
        'El símbolo de la acción no puede estar vacío.',
      );
    }

    return MarketQuote(
      symbol: normalizedSymbol,
      companyName: normalizedSymbol == 'AAPL'
          ? 'Apple Inc.'
          : 'Empresa de prueba',
      currentPrice: 226.40,
      change: 2.15,
      changePercentage: 0.96,
      updatedAt: DateTime.now(),
    );
  }
}