import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/models/market_context.dart';

void main() {
  test('MarketContext conserva correctamente sus datos', () {
    final updatedAt = DateTime(2026, 8, 24, 12, 30);

    final context = MarketContext(
      updatedAt: updatedAt,
      assetsAnalyzed: 500,
      advancingPercentage: 62.5,
      decliningPercentage: 37.5,
      volatility: 18.4,
      sentiment: 'positive',
      summary: 'El mercado presenta un sesgo positivo.',
    );

    expect(context.updatedAt, updatedAt);
    expect(context.assetsAnalyzed, 500);
    expect(context.advancingPercentage, 62.5);
    expect(context.decliningPercentage, 37.5);
    expect(context.volatility, 18.4);
    expect(context.sentiment, 'positive');
    expect(context.summary, 'El mercado presenta un sesgo positivo.');
  });

  test('MarketContext permite volatilidad desconocida', () {
    final context = MarketContext(
      updatedAt: DateTime(2026, 8, 24),
      assetsAnalyzed: 300,
      advancingPercentage: 50,
      decliningPercentage: 50,
      volatility: null,
      sentiment: 'neutral',
      summary: 'El mercado se encuentra equilibrado.',
    );

    expect(context.volatility, isNull);
  });
}
