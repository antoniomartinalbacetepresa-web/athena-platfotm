import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/services/mock_market_context_service.dart';

void main() {
  test(
    'MockMarketContextService devuelve un contexto de mercado válido',
    () async {
      const service = MockMarketContextService();

      final result = await service.getMarketContext();

      expect(result.assetsAnalyzed, 500);
      expect(result.advancingPercentage, 62.5);
      expect(result.decliningPercentage, 37.5);
      expect(result.volatility, 18.4);
      expect(result.sentiment, 'positive');
      expect(result.summary, 'El mercado presenta un sesgo positivo.');
    },
  );
}
