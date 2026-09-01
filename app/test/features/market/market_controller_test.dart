import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/controllers/market_controller.dart';
import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/repositories/market_repository.dart';

class FakeMarketRepository implements MarketRepository {
  @override
  Future<MarketQuote> getQuote(String symbol) async {
    return MarketQuote(
      symbol: symbol.trim().toUpperCase(),
      companyName: 'Apple Inc.',
      currentPrice: 305.93,
      change: 0.67,
      changePercentage: 0.21949,
      updatedAt: DateTime.utc(2026, 1, 1),
    );
  }
}

void main() {
  test(
    'MarketController carga correctamente una cotización',
    () async {
      final controller = MarketController(
        repository: FakeMarketRepository(),
      );

      await controller.loadQuote('aapl');

      expect(controller.isLoading, isFalse);
      expect(controller.error, isNull);
      expect(controller.quote, isNotNull);

      expect(controller.quote!.symbol, 'AAPL');
      expect(controller.quote!.companyName, 'Apple Inc.');
      expect(controller.quote!.currentPrice, 305.93);
      expect(controller.quote!.changePercentage, 0.21949);
    },
  );

  test(
    'MarketController notifica los cambios durante la carga',
    () async {
      final controller = MarketController(
        repository: FakeMarketRepository(),
      );

      var notifications = 0;

      controller.addListener(() {
        notifications++;
      });

      await controller.loadQuote('AAPL');

      expect(notifications, greaterThanOrEqualTo(2));
      expect(controller.isLoading, isFalse);
    },
  );
}