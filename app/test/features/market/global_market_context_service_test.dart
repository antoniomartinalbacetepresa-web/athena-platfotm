import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/models/market_region.dart';
import 'package:app/features/market/models/market_universe_asset.dart';
import 'package:app/features/market/models/regional_market_context.dart';
import 'package:app/features/market/models/regional_market_weights.dart';
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
          assetsAnalyzed: 3,
          advancingPercentage: 70,
          decliningPercentage: 30,
          sentiment: 'positive',
          summary: 'América presenta un sesgo positivo.',
          updatedAt: DateTime(2026, 8, 25),
        );

      case MarketRegion.europe:
        return RegionalMarketContext(
          region: region.key,
          displayName: 'Europa',
          assetsAnalyzed: 2,
          advancingPercentage: 50,
          decliningPercentage: 50,
          sentiment: 'neutral',
          summary: 'Europa presenta un comportamiento mixto.',
          updatedAt: DateTime(2026, 8, 25),
        );

      case MarketRegion.asia:
        return RegionalMarketContext(
          region: region.key,
          displayName: 'Asia',
          assetsAnalyzed: 3,
          advancingPercentage: 30,
          decliningPercentage: 70,
          sentiment: 'negative',
          summary: 'Asia presenta un sesgo negativo.',
          updatedAt: DateTime(2026, 8, 25),
        );
    }
  }
}

class MissingRegionRegionalMarketContextService
    implements RegionalMarketContextService {
  @override
  Future<RegionalMarketContext> getRegionalContext({
    required MarketRegion region,
  }) async {
    if (region == MarketRegion.america) {
      return RegionalMarketContext(
        region: region.key,
        displayName: 'América',
        assetsAnalyzed: 3,
        advancingPercentage: 70,
        decliningPercentage: 30,
        sentiment: 'positive',
        summary: 'América presenta un sesgo positivo.',
        updatedAt: DateTime(2026, 8, 25),
      );
    }

    return RegionalMarketContext(
      region: 'unexpected',
      displayName: 'Región inesperada',
      assetsAnalyzed: 2,
      advancingPercentage: 50,
      decliningPercentage: 50,
      sentiment: 'neutral',
      summary: 'Contexto inesperado.',
      updatedAt: DateTime(2026, 8, 25),
    );
  }
}

class FakeMarketUniverseRepository
    implements MarketUniverseRepository {
  @override
  Future<List<MarketUniverseAsset>> getUniverse() async {
    return const [
      MarketUniverseAsset(
        symbol: 'USA',
        companyName: 'USA Company',
        marketCap: 600,
        country: 'United States',
      ),
      MarketUniverseAsset(
        symbol: 'ESP',
        companyName: 'Spain Company',
        marketCap: 200,
        country: 'Spain',
      ),
      MarketUniverseAsset(
        symbol: 'JPN',
        companyName: 'Japan Company',
        marketCap: 200,
        country: 'Japan',
      ),
    ];
  }
}

class EmptyMarketUniverseRepository
    implements MarketUniverseRepository {
  @override
  Future<List<MarketUniverseAsset>> getUniverse() async {
    return const [];
  }
}

void main() {
  group('GlobalMarketDataService', () {
    test(
      'calcula los pesos globales a partir del universo de mercado',
      () async {
        final service = GlobalMarketDataService(
          regionalMarketContextService:
              FakeRegionalMarketContextService(),
          globalMarketContextService:
              const GlobalMarketContextService(),
          marketUniverseRepository:
              FakeMarketUniverseRepository(),
          regionalMarketWeightService:
              const RegionalMarketWeightService(),
        );

        final context = await service.getGlobalContext();

        expect(
          context.americaWeight,
          closeTo(0.60, 0.000001),
        );

        expect(
          context.europeWeight,
          closeTo(0.20, 0.000001),
        );

        expect(
          context.asiaWeight,
          closeTo(0.20, 0.000001),
        );

        expect(
          context.weightSource,
          RegionalMarketWeightSource.calculated,
        );

        expect(context.weightConfidence, 1.0);
        expect(context.hasCalculatedWeights, isTrue);
        expect(context.isUsingBaselineWeights, isFalse);

        expect(
          context.america.region,
          MarketRegion.america.key,
        );

        expect(
          context.europe.region,
          MarketRegion.europe.key,
        );

        expect(
          context.asia.region,
          MarketRegion.asia.key,
        );

        expect(
          context.advancingPercentage,
          closeTo(
            (70.0 * 0.60) +
                (50.0 * 0.20) +
                (30.0 * 0.20),
            0.000001,
          ),
        );

        expect(
          context.decliningPercentage,
          closeTo(
            (30.0 * 0.60) +
                (50.0 * 0.20) +
                (70.0 * 0.20),
            0.000001,
          ),
        );

        expect(context.sentiment, 'positive');
        expect(context.summary, isNotEmpty);
      },
    );

    test(
      'obtiene los tres contextos regionales',
      () async {
        final service = GlobalMarketDataService(
          regionalMarketContextService:
              FakeRegionalMarketContextService(),
          globalMarketContextService:
              const GlobalMarketContextService(),
          marketUniverseRepository:
              FakeMarketUniverseRepository(),
          regionalMarketWeightService:
              const RegionalMarketWeightService(),
        );

        final context = await service.getGlobalContext();

        expect(context.america, isNotNull);
        expect(context.europe, isNotNull);
        expect(context.asia, isNotNull);
      },
    );

    test(
      'falla cuando no se puede construir uno de los contextos regionales',
      () async {
        final service = GlobalMarketDataService(
          regionalMarketContextService:
              MissingRegionRegionalMarketContextService(),
          globalMarketContextService:
              const GlobalMarketContextService(),
          marketUniverseRepository:
              FakeMarketUniverseRepository(),
          regionalMarketWeightService:
              const RegionalMarketWeightService(),
        );

        expect(
          service.getGlobalContext,
          throwsStateError,
        );
      },
    );

    test(
      'utiliza baseline cuando el universo no permite calcular pesos regionales',
      () async {
        final service = GlobalMarketDataService(
          regionalMarketContextService:
              FakeRegionalMarketContextService(),
          globalMarketContextService:
              const GlobalMarketContextService(),
          marketUniverseRepository:
              EmptyMarketUniverseRepository(),
          regionalMarketWeightService:
              const RegionalMarketWeightService(),
        );

        final context = await service.getGlobalContext();

        expect(
          context.americaWeight,
          closeTo(0.54, 0.000001),
        );

        expect(
          context.europeWeight,
          closeTo(0.16, 0.000001),
        );

        expect(
          context.asiaWeight,
          closeTo(0.30, 0.000001),
        );

        expect(
          context.weightSource,
          RegionalMarketWeightSource.baseline,
        );

        expect(
          context.weightConfidence,
          closeTo(0.35, 0.000001),
        );

        expect(context.hasCalculatedWeights, isFalse);
        expect(context.isUsingBaselineWeights, isTrue);

        expect(
          context.summary,
          contains('referencia estructural'),
        );
      },
    );

    test(
      'el baseline regional forma una distribución válida',
      () {
        expect(
          RegionalMarketWeights.baseline.isValid,
          isTrue,
        );

        expect(
          RegionalMarketWeights.baseline.total,
          closeTo(1.0, 0.000001),
        );

        expect(
          RegionalMarketWeights.baseline.source,
          RegionalMarketWeightSource.baseline,
        );
      },
    );
  });
}