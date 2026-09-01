import '../../analysis/data/datasources/fmp_stock_market_data_source.dart';
import '../models/market_quote.dart';
import 'market_service.dart';

class FmpMarketService implements MarketService {
  final FmpStockMarketDataSource dataSource;

  const FmpMarketService({
    required this.dataSource,
  });

  @override
  Future<MarketQuote> getQuote(String symbol) async {
    final normalizedSymbol = symbol.trim().toUpperCase();

    if (normalizedSymbol.isEmpty) {
      throw ArgumentError(
        'El símbolo de la acción no puede estar vacío.',
      );
    }

    final data = await dataSource.getStockAnalysisData(
      normalizedSymbol,
    );

    final currentPrice = data.currentPrice;
    final previousClose = data.previousClose;
    final changePercentage = data.dayChangePercent;

    if (currentPrice == null) {
      throw FormatException(
        'FMP no devolvió el precio actual de $normalizedSymbol.',
      );
    }

    if (previousClose == null) {
      throw FormatException(
        'FMP no devolvió el cierre anterior de $normalizedSymbol.',
      );
    }

    if (changePercentage == null) {
      throw FormatException(
        'FMP no devolvió el cambio porcentual de $normalizedSymbol.',
      );
    }

    return MarketQuote(
      symbol: normalizedSymbol,
      companyName: data.companyName,
      currentPrice: currentPrice,
      change: currentPrice - previousClose,
      changePercentage: changePercentage,
      marketCap: data.marketCap,
      updatedAt: data.dataTimestamp ?? DateTime.now(),
    );
  }
}