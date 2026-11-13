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

    // An adjusted historical close is not an observed quote price. Never
    // substitute it silently: corporate-action adjustments can differ.
    final currentPrice = point.close;
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
      currency: point.currency,
      exchange: point.exchange,
      quoteType: point.quoteType,
      exchangeTimezone: point.exchangeTimezone,
      updatedAt: point.timestamp,
      sourceProvider: point.sourceProvider,
      retrievedAt: point.retrievedAt,
      quoteMode: point.quoteMode,
      priceSessionDate: point.priceSessionDate,
      realTimePriceVerified: point.realTimePriceVerified,
      historicalPointInTimeEligible: point.historicalPointInTimeEligible,
      instrumentId: point.instrumentId,
      canonicalIdentityStatus: point.canonicalIdentityStatus,
    );
  }
}
