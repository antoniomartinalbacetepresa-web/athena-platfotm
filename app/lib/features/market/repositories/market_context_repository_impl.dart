import '../models/market_context.dart';
import '../services/market_context_service.dart';
import 'market_context_repository.dart';

class MarketContextRepositoryImpl implements MarketContextRepository {
  final MarketContextService marketContextService;

  const MarketContextRepositoryImpl({
    required this.marketContextService,
  });

  @override
  Future<MarketContext> getMarketContext() {
    return marketContextService.getMarketContext();
  }
}