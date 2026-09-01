import '../models/market_context.dart';

abstract interface class MarketContextService {
  Future<MarketContext> getMarketContext();
}
