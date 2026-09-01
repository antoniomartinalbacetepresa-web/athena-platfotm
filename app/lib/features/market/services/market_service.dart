import '../models/market_quote.dart';

abstract interface class MarketService {
  Future<MarketQuote> getQuote(String symbol);
}