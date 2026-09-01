import '../data/providers/market_data_provider.dart';
import '../models/market_quote.dart';
import 'market_service.dart';

/// Servicio de mercado basado en un proveedor [MarketDataProvider].
///
/// Convierte el modelo técnico del proveedor ([MarketDataPoint])
/// en el modelo que utiliza el resto de la aplicación ([MarketQuote]).
///
/// Este servicio no contiene lógica de inversión.
class TwelveDataMarketService implements MarketService {
  final MarketDataProvider provider;

  const TwelveDataMarketService({
    required this.provider,
  });

  @override
  Future<MarketQuote> getQuote(String symbol) async {
    final normalizedSymbol = symbol.trim().toUpperCase();

    if (normalizedSymbol.isEmpty) {
      throw ArgumentError(
        'El símbolo de la acción no puede estar vacío.',
      );
    }

    final dataPoint = await provider.getQuote(normalizedSymbol);

    if (dataPoint == null) {
      throw FormatException(
        'Twelve Data no devolvió una cotización válida '
        'para $normalizedSymbol.',
      );
    }

    if (dataPoint.close == null) {
      throw FormatException(
        'Twelve Data no devolvió el precio actual '
        'de $normalizedSymbol.',
      );
    }

    if (dataPoint.changePercentage == null) {
      throw FormatException(
        'Twelve Data no devolvió el cambio porcentual '
        'de $normalizedSymbol.',
      );
    }

    final currentPrice = dataPoint.close!;
    final changePercentage = dataPoint.changePercentage!;

    final change = dataPoint.change ??
        currentPrice * (changePercentage / 100.0);

    return MarketQuote(
      symbol: dataPoint.symbol,
      companyName: dataPoint.symbol,
      currentPrice: currentPrice,
      change: change,
      changePercentage: changePercentage,
      marketCap: null,
      updatedAt: dataPoint.timestamp,
    );
  }
}