import 'dart:async';

import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/controllers/global_market_context_controller.dart';
import 'package:app/features/market/models/global_market_context.dart';
import 'package:app/features/market/models/market_region.dart';
import 'package:app/features/market/models/market_universe_asset.dart';
import 'package:app/features/market/models/regional_market_context.dart';
import 'package:app/features/market/repositories/market_universe_repository.dart';
import 'package:app/features/market/services/global_market_context_service.dart';
import 'package:app/features/market/services/global_market_data_service.dart';
import 'package:app/features/market/services/regional_market_context_service.dart';
import 'package:app/features/market/services/regional_market_weight_service.dart';

class FakeRegionalMarketContextService implements RegionalMarketContextService {
  @override
  Future<RegionalMarketContext> getRegionalContext({required MarketRegion region}) async {
    switch (region) {
      case MarketRegion.america:
        return RegionalMarketContext(region: region.key, displayName: 'América', assetsAnalyzed: 100, advancingPercentage: 66.67, decliningPercentage: 33.33, sentiment: 'positive', summary: 'América test', updatedAt: DateTime(2026, 1, 1));
      case MarketRegion.europe:
        return RegionalMarketContext(region: region.key, displayName: 'Europa', assetsAnalyzed: 100, advancingPercentage: 50, decliningPercentage: 50, sentiment: 'neutral', summary: 'Europa test', updatedAt: DateTime(2026, 1, 1));
      case MarketRegion.asia:
        return RegionalMarketContext(region: region.key, displayName: 'Asia', assetsAnalyzed: 100, advancingPercentage: 33.33, decliningPercentage: 66.67, sentiment: 'negative', summary: 'Asia test', updatedAt: DateTime(2026, 1, 1));
    }
  }
}

class FakeMarketUniverseRepository implements MarketUniverseRepository {
  const FakeMarketUniverseRepository();
  @override
  Future<List<MarketUniverseAsset>> getUniverse() async => const [
        MarketUniverseAsset(symbol: 'USA', companyName: 'America Test Company', marketCap: 500, country: 'United States'),
        MarketUniverseAsset(symbol: 'ESP', companyName: 'Europe Test Company', marketCap: 300, country: 'Spain'),
        MarketUniverseAsset(symbol: 'JPN', companyName: 'Asia Test Company', marketCap: 200, country: 'Japan'),
      ];
}

class SequencedGlobalMarketDataService extends GlobalMarketDataService {
  SequencedGlobalMarketDataService({required this.first, required this.second})
      : super(
          regionalMarketContextService: FakeRegionalMarketContextService(),
          globalMarketContextService: const GlobalMarketContextService(),
          marketUniverseRepository: const FakeMarketUniverseRepository(),
          regionalMarketWeightService: const RegionalMarketWeightService(),
        );

  final GlobalMarketContext first;
  final Future<GlobalMarketContext> second;
  var calls = 0;

  @override
  Future<GlobalMarketContext> getGlobalContext() {
    calls += 1;
    return calls == 1 ? Future.value(first) : second;
  }
}

class PendingGlobalMarketDataService extends GlobalMarketDataService {
  PendingGlobalMarketDataService()
      : super(
          regionalMarketContextService: FakeRegionalMarketContextService(),
          globalMarketContextService: const GlobalMarketContextService(),
          marketUniverseRepository: const FakeMarketUniverseRepository(),
          regionalMarketWeightService: const RegionalMarketWeightService(),
        );

  final requests = <Completer<GlobalMarketContext>>[];

  @override
  Future<GlobalMarketContext> getGlobalContext() {
    final request = Completer<GlobalMarketContext>();
    requests.add(request);
    return request.future;
  }
}

void main() {
  GlobalMarketDataService createService() => GlobalMarketDataService(
        regionalMarketContextService: FakeRegionalMarketContextService(),
        globalMarketContextService: const GlobalMarketContextService(),
        marketUniverseRepository: const FakeMarketUniverseRepository(),
        regionalMarketWeightService: const RegionalMarketWeightService(),
      );

  group('GlobalMarketContextController', () {
    test('carga el contexto global correctamente', () async {
      final controller = GlobalMarketContextController(service: createService());
      expect(controller.context, isNull);
      expect(controller.isLoading, isFalse);
      expect(controller.error, isNull);
      await controller.loadGlobalContext();
      expect(controller.context, isNotNull);
      expect(controller.isLoading, isFalse);
      expect(controller.error, isNull);
      expect(controller.context!.americaWeight, closeTo(0.50, 0.000001));
      expect(controller.context!.europeWeight, closeTo(0.30, 0.000001));
      expect(controller.context!.asiaWeight, closeTo(0.20, 0.000001));
    });

    test('carga los tres contextos regionales', () async {
      final controller = GlobalMarketContextController(service: createService());
      await controller.loadGlobalContext();
      expect(controller.context, isNotNull);
      expect(controller.context!.america.region, MarketRegion.america.key);
      expect(controller.context!.europe.region, MarketRegion.europe.key);
      expect(controller.context!.asia.region, MarketRegion.asia.key);
    });

    test('clear elimina el contexto y el error', () async {
      final controller = GlobalMarketContextController(service: createService());
      await controller.loadGlobalContext();
      controller.clear();
      expect(controller.context, isNull);
      expect(controller.error, isNull);
      expect(controller.isLoading, isFalse);
    });

    test('refresh oculta inmediatamente el contexto anterior mientras espera datos nuevos', () async {
      final initial = await createService().getGlobalContext();
      final pending = Completer<GlobalMarketContext>();
      final service = SequencedGlobalMarketDataService(first: initial, second: pending.future);
      final controller = GlobalMarketContextController(service: service);

      await controller.loadGlobalContext();
      expect(controller.context, same(initial));

      final refresh = controller.loadGlobalContext();
      expect(controller.isLoading, isTrue);
      expect(controller.context, isNull);
      expect(controller.error, isNull);

      pending.complete(initial);
      await refresh;
      expect(controller.isLoading, isFalse);
      expect(controller.context, same(initial));
    });

    test('clear invalidates an in-flight market response before a new load', () async {
      final initial = await createService().getGlobalContext();
      final pending = Completer<GlobalMarketContext>();
      final service = SequencedGlobalMarketDataService(
        first: initial,
        second: pending.future,
      );
      final controller = GlobalMarketContextController(service: service);
      await controller.loadGlobalContext();

      final staleRequest = controller.loadGlobalContext();
      expect(controller.isLoading, isTrue);
      controller.clear();
      expect(controller.context, isNull);
      expect(controller.isLoading, isFalse);

      pending.complete(initial);
      await staleRequest;
      expect(controller.context, isNull);
      expect(controller.error, isNull);
      expect(controller.isLoading, isFalse);

      await controller.loadGlobalContext();
      expect(service.calls, 3);
      expect(controller.context, same(initial));
      controller.dispose();
    });

    test('disposed controller ignores a late market response', () async {
      final initial = await createService().getGlobalContext();
      final replacement = await createService().getGlobalContext();
      final pending = Completer<GlobalMarketContext>();
      final service = SequencedGlobalMarketDataService(
        first: initial,
        second: pending.future,
      );
      final controller = GlobalMarketContextController(service: service);
      await controller.loadGlobalContext();
      final staleRequest = controller.loadGlobalContext();
      controller.dispose();

      pending.complete(replacement);
      await staleRequest;
      // A refresh clears the prior snapshot before awaiting the response.
      // Disposal must not publish the late replacement.
      expect(controller.context, isNull);
    });

    test('explicit refresh supersedes a stalled market request', () async {
      final service = PendingGlobalMarketDataService();
      final controller = GlobalMarketContextController(service: service);
      final expected = await createService().getGlobalContext();
      final stale = controller.loadGlobalContext();
      final current = controller.loadGlobalContext();
      expect(service.requests.length, 2);
      expect(controller.context, isNull);
      expect(controller.isLoading, isTrue);

      service.requests[1].complete(expected);
      await current;
      service.requests[0].completeError(StateError('private-market-url'));
      await stale;
      expect(controller.context, same(expected));
      expect(controller.error, isNull);
      expect(controller.isLoading, isFalse);
      controller.dispose();
    });

    test('late success cannot replace a newer market failure', () async {
      final service = PendingGlobalMarketDataService();
      final controller = GlobalMarketContextController(service: service);
      final oldContext = await createService().getGlobalContext();
      final stale = controller.loadGlobalContext();
      final current = controller.loadGlobalContext();

      service.requests[1].completeError(StateError('private-market-url'));
      await current;
      service.requests[0].complete(oldContext);
      await stale;
      expect(controller.context, isNull);
      expect(controller.error, contains('No se pudo verificar'));
      expect(controller.error, isNot(contains('private-market-url')));
      expect(controller.isLoading, isFalse);
      controller.dispose();
    });
  });
}
