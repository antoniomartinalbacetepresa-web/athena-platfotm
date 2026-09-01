import '../models/market_context.dart';

abstract interface class MarketContextRepository {
  Future<MarketContext> getMarketContext();
}
