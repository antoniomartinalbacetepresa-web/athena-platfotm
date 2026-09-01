import '../models/market_quote.dart';
import '../services/market_service.dart';
import 'market_repository.dart';

class MarketRepositoryImpl implements MarketRepository {
  final MarketService marketService;

  MarketRepositoryImpl({
    required this.marketService,
  });

  @override
  Future<MarketQuote> getQuote(String symbol) {
    return marketService.getQuote(symbol);
  }
}