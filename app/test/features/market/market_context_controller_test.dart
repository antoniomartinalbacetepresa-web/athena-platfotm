import 'dart:async';

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

class PendingMarketContextRepository implements MarketContextRepository {
  final requests = <Completer<MarketContext>>[];

  @override
  Future<MarketContext> getMarketContext() {
    final request = Completer<MarketContext>();
    requests.add(request);
    return request.future;
  }
}

MarketContext sampleContext(int assets) => MarketContext(
      updatedAt: DateTime.utc(2026, 10, 29),
      assetsAnalyzed: assets,
      advancingPercentage: 55,
      decliningPercentage: 45,
      volatility: 20,
      sentiment: 'neutral',
      summary: 'Contexto de prueba',
    );

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
  test('refresh supersedes an in-flight response and clears stale evidence', () async {
    final repository = PendingMarketContextRepository();
    final controller = MarketContextController(repository: repository);
    final stale = controller.loadMarketContext();
    final current = controller.loadMarketContext();
    expect(repository.requests.length, 2);
    expect(controller.isLoading, isTrue);
    expect(controller.context, isNull);

    repository.requests[1].complete(sampleContext(200));
    await current;
    expect(controller.context!.assetsAnalyzed, 200);
    repository.requests[0].complete(sampleContext(100));
    await stale;
    expect(controller.context!.assetsAnalyzed, 200);
    expect(controller.error, isNull);
    expect(controller.isLoading, isFalse);
    controller.dispose();
  });

  test('stale provider failure cannot erase newer evidence or expose details', () async {
    final repository = PendingMarketContextRepository();
    final controller = MarketContextController(repository: repository);
    final stale = controller.loadMarketContext();
    final current = controller.loadMarketContext();
    repository.requests[1].complete(sampleContext(300));
    await current;
    repository.requests[0].completeError(StateError('private-provider-token'));
    await stale;
    expect(controller.context!.assetsAnalyzed, 300);
    expect(controller.error, isNull);
    controller.dispose();
  });

  test('clear and disposal invalidate in-flight responses', () async {
    final repository = PendingMarketContextRepository();
    final controller = MarketContextController(repository: repository);
    final cleared = controller.loadMarketContext();
    controller.clear();
    repository.requests[0].complete(sampleContext(100));
    await cleared;
    expect(controller.context, isNull);
    expect(controller.isLoading, isFalse);

    final disposed = controller.loadMarketContext();
    controller.dispose();
    repository.requests[1].complete(sampleContext(200));
    await disposed;
    expect(controller.context, isNull);
    await controller.loadMarketContext();
    expect(repository.requests.length, 2);
  });
}
