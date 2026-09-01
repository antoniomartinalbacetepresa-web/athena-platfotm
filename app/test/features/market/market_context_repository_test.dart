import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/models/market_context.dart';
import 'package:app/features/market/repositories/market_context_repository_impl.dart';
import 'package:app/features/market/services/market_context_service.dart';

class FakeMarketContextService implements MarketContextService {
  @override
  Future<MarketContext> getMarketContext() async {
    return MarketContext(
      updatedAt: DateTime(2026, 8, 24, 12, 30),
      assetsAnalyzed: 100,
      advancingPercentage: 55,
      decliningPercentage: 45,
      volatility: 20,
      sentiment: 'positive',
      summary: 'Mercado con sesgo positivo.',
    );
  }
}

void main() {
  test('MarketContextRepository devuelve el contexto del servicio', () async {
    final service = FakeMarketContextService();

    final repository = MarketContextRepositoryImpl(
      marketContextService: service,
    );

    final result = await repository.getMarketContext();

    expect(result.assetsAnalyzed, 100);
    expect(result.advancingPercentage, 55);
    expect(result.decliningPercentage, 45);
    expect(result.volatility, 20);
    expect(result.sentiment, 'positive');
    expect(result.summary, 'Mercado con sesgo positivo.');
  });
}
