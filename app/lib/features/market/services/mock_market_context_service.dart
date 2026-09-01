import '../models/market_context.dart';
import 'market_context_service.dart';

class MockMarketContextService implements MarketContextService {
  const MockMarketContextService();

  @override
  Future<MarketContext> getMarketContext() async {
    return MarketContext(
      updatedAt: DateTime.now(),
      assetsAnalyzed: 500,
      advancingPercentage: 62.5,
      decliningPercentage: 37.5,
      volatility: 18.4,
      sentiment: 'positive',
      summary: 'El mercado presenta un sesgo positivo.',
    );
  }
}
