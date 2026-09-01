import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/controllers/global_market_context_controller.dart';
import 'package:app/features/market/models/market_region.dart';
import 'package:app/features/market/models/market_universe_asset.dart';
import 'package:app/features/market/models/regional_market_context.dart';
import 'package:app/features/market/repositories/market_universe_repository.dart';
import 'package:app/features/market/services/global_market_context_service.dart';
import 'package:app/features/market/services/global_market_data_service.dart';
import 'package:app/features/market/services/regional_market_context_service.dart';
import 'package:app/features/market/services/regional_market_weight_service.dart';

class FakeRegionalMarketContextService
    implements RegionalMarketContextService {
  @override
  Future<RegionalMarketContext> getRegionalContext({
    required MarketRegion region,
  }) async {
    switch (region) {
      case MarketRegion.america:
        return RegionalMarketContext(
          region: region.key,
          displayName: 'América',
          assetsAnalyzed: 100,
          advancingPercentage: 66.67,
          decliningPercentage: 33.33,
          sentiment: 'positive',
          summary: 'América test',
          updatedAt: DateTime(2026, 1, 1),
        );

      case MarketRegion.europe:
        return RegionalMarketContext(
          region: region.key,
          displayName: 'Europa',
          assetsAnalyzed: 100,
          advancingPercentage: 50,
          decliningPercentage: 50,
          sentiment: 'neutral',
          summary: 'Europa test',
          updatedAt: DateTime(2026, 1, 1),
        );

      case MarketRegion.asia:
        return RegionalMarketContext(
          region: region.key,
          displayName: 'Asia',
          assetsAnalyzed: 100,
          advancingPercentage: 33.33,
          decliningPercentage: 66.67,
          sentiment: 'negative',
          summary: 'Asia test',
          updatedAt: DateTime(2026, 1, 1),
        );
    }
  }
}

class FakeMarketUniverseRepository implements MarketUniverseRepository {
  const FakeMarketUniverseRepository();

  @override
  Future<List<MarketUniverseAsset>> getUniverse() async {
    return const [
      MarketUniverseAsset(
        symbol: 'USA',
        companyName: 'America Test Company',
        marketCap: 500,
        country: 'United States',
      ),
      MarketUniverseAsset(
        symbol: 'ESP',
        companyName: 'Europe Test Company',
        marketCap: 300,
        country: 'Spain',
      ),
      MarketUniverseAsset(
        symbol: 'JPN',
        companyName: 'Asia Test Company',
        marketCap: 200,
        country: 'Japan',
      ),
    ];
  }
}

void main() {
  GlobalMarketDataService createService() {
    return GlobalMarketDataService(
      regionalMarketContextService:
          FakeRegionalMarketContextService(),
      globalMarketContextService:
          const GlobalMarketContextService(),
      marketUniverseRepository:
          const FakeMarketUniverseRepository(),
      regionalMarketWeightService:
          const RegionalMarketWeightService(),
    );
  }

  group('GlobalMarketContextController', () {
    test(
      'carga el contexto global correctamente',
      () async {
        final controller = GlobalMarketContextController(
          service: createService(),
        );

        expect(controller.context, isNull);
        expect(controller.isLoading, isFalse);
        expect(controller.error, isNull);

        await controller.loadGlobalContext();

        expect(controller.context, isNotNull);
        expect(controller.isLoading, isFalse);
        expect(controller.error, isNull);

        expect(
          controller.context!.americaWeight,
          closeTo(0.50, 0.000001),
        );

        expect(
          controller.context!.europeWeight,
          closeTo(0.30, 0.000001),
        );

        expect(
          controller.context!.asiaWeight,
          closeTo(0.20, 0.000001),
        );
      },
    );

    test(
      'carga los tres contextos regionales',
      () async {
        final controller = GlobalMarketContextController(
          service: createService(),
        );

        await controller.loadGlobalContext();

        expect(controller.context, isNotNull);

        expect(
          controller.context!.america.region,
          MarketRegion.america.key,
        );

        expect(
          controller.context!.europe.region,
          MarketRegion.europe.key,
        );

        expect(
          controller.context!.asia.region,
          MarketRegion.asia.key,
        );
      },
    );

    test(
      'clear elimina el contexto y el error',
      () async {
        final controller = GlobalMarketContextController(
          service: createService(),
        );

        await controller.loadGlobalContext();

        controller.clear();

        expect(controller.context, isNull);
        expect(controller.error, isNull);
        expect(controller.isLoading, isFalse);
      },
    );
  });
}