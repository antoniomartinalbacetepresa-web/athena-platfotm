import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/controllers/market_context_controller.dart';
import 'package:app/features/market/models/market_context.dart';
import 'package:app/features/market/repositories/market_context_repository.dart';

class FakeMarketContextRepository implements MarketContextRepository {
  final bool shouldFail;

  FakeMarketContextRepository({this.shouldFail = false});

  @override
  Future<MarketContext> getMarketContext() async {
    if (shouldFail) {
      throw Exception('Error de prueba');
    }

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
  test(
    'MarketContextController conserva el contexto cuando el repositorio responde correctamente',
    () async {
      final repository = FakeMarketContextRepository();

      final controller = MarketContextController(repository: repository);

      await controller.loadMarketContext();

      expect(controller.isLoading, false);
      expect(controller.error, isNull);
      expect(controller.context, isNotNull);

      expect(controller.context!.assetsAnalyzed, 100);
      expect(controller.context!.advancingPercentage, 55);
      expect(controller.context!.decliningPercentage, 45);
      expect(controller.context!.volatility, 20);
      expect(controller.context!.sentiment, 'positive');
      expect(controller.context!.summary, 'Mercado con sesgo positivo.');

      controller.dispose();
    },
  );

  test(
    'MarketContextController gestiona correctamente un error del repositorio',
    () async {
      final repository = FakeMarketContextRepository(shouldFail: true);

      final controller = MarketContextController(repository: repository);

      await controller.loadMarketContext();

      expect(controller.isLoading, false);
      expect(controller.context, isNull);
      expect(controller.error, 'No se pudo obtener el contexto del mercado.');

      controller.dispose();
    },
  );
}
