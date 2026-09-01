import '../data/providers/athena_backend_market_data_provider.dart';
import '../models/market_quote.dart';
import 'market_service.dart';

/// Adapta el contrato de datos normalizado del backend al dominio de mercado.
class AthenaBackendMarketService implements MarketService {
  final AthenaBackendMarketDataProvider provider;

  const AthenaBackendMarketService({required this.provider});

  @override
  Future<MarketQuote> getQuote(String symbol) async {
    final point = await provider.getQuote(symbol);

    if (point == null) {
      throw StateError('El backend no devolvió cotización para $symbol.');
    }

    final currentPrice = point.close ?? point.adjustedClose;
    if (currentPrice == null) {
      throw StateError(
        'La cotización de ${point.symbol} no contiene precio actual.',
      );
    }

    return MarketQuote(
      symbol: point.symbol,
      companyName: point.symbol,
      currentPrice: currentPrice,
      change: point.change ?? 0,
      changePercentage: point.changePercentage ?? 0,
      updatedAt: point.timestamp,
    );
  }
}
