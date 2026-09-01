import '../models/global_market_context.dart';
import '../models/market_region.dart';
import '../models/market_universe_asset.dart';
import '../models/market_universe_status.dart';
import '../models/regional_market_context.dart';
import '../models/regional_market_weights.dart';
import '../repositories/market_universe_repository.dart';
import 'global_market_context_service.dart';
import 'regional_market_context_service.dart';
import 'regional_market_weight_service.dart';

abstract class MarketUniverseStatusProvider {
  Future<MarketUniverseStatus> getStatus();
}

/// Orquesta la construcción del contexto global de mercado.
///
/// El contexto global combina dos fuentes conceptualmente diferentes:
///
/// 1. Contextos regionales:
///    describen el comportamiento actual de los benchmarks.
///
/// 2. Pesos regionales:
///    representan la distribución de capitalización del universo
///    de mercado analizado.
///
/// Los benchmarks se utilizan para medir comportamiento.
/// El universo de mercado se utiliza para calcular pesos únicamente cuando
/// el backend declara que la metodología de selección es comparable entre
/// regiones.
///
/// Cuando todavía no existe suficiente información o el muestreo no es apto
/// para ponderación, ATHENA TYCHE utiliza un baseline estructural provisional.
///
/// El origen de los pesos y el estado del universo quedan registrados en
/// [GlobalMarketContext] para no confundir una estimación provisional con un
/// cálculo respaldado por metodología representativa.
///
/// Este servicio no contiene lógica de inversión ni recomendaciones.
class GlobalMarketDataService {
  final RegionalMarketContextService regionalMarketContextService;
  final GlobalMarketContextService globalMarketContextService;
  final MarketUniverseRepository marketUniverseRepository;
  final RegionalMarketWeightService regionalMarketWeightService;
  final MarketUniverseStatusProvider? marketUniverseStatusProvider;

  const GlobalMarketDataService({
    required this.regionalMarketContextService,
    required this.globalMarketContextService,
    required this.marketUniverseRepository,
    required this.regionalMarketWeightService,
    this.marketUniverseStatusProvider,
  });

  /// Construye el contexto global actual del mercado.
  Future<GlobalMarketContext> getGlobalContext() async {
    const regions = [
      MarketRegion.america,
      MarketRegion.europe,
      MarketRegion.asia,
    ];

    final regionalContextsFuture = Future.wait(
      regions.map(
        (region) => regionalMarketContextService.getRegionalContext(
          region: region,
        ),
      ),
    );

    final universeFuture = marketUniverseRepository.getUniverse();
    final universeStatusFuture = marketUniverseStatusProvider?.getStatus();

    final regionalContexts = await regionalContextsFuture;
    final universe = await universeFuture;
    final universeStatus = universeStatusFuture == null
        ? const MarketUniverseStatus.fallback()
        : await universeStatusFuture;

    final contextsByRegion = <String, RegionalMarketContext>{
      for (final context in regionalContexts) context.region: context,
    };

    final america = contextsByRegion[MarketRegion.america.key];
    final europe = contextsByRegion[MarketRegion.europe.key];
    final asia = contextsByRegion[MarketRegion.asia.key];

    if (america == null || europe == null || asia == null) {
      throw StateError(
        'No se pudieron construir todos los contextos regionales.',
      );
    }

    final regionalWeights = _resolveRegionalWeights(
      universe,
      enforceBackendReadiness: marketUniverseStatusProvider != null,
      universeStatus: universeStatus,
    );

    _validateRegionalWeights(regionalWeights);

    final baseContext = globalMarketContextService.build(
      america: america,
      europe: europe,
      asia: asia,
      americaWeight: regionalWeights.america,
      europeWeight: regionalWeights.europe,
      asiaWeight: regionalWeights.asia,
      weightSource: regionalWeights.source,
      weightConfidence: regionalWeights.confidence,
    );

    return GlobalMarketContext(
      updatedAt: baseContext.updatedAt,
      america: baseContext.america,
      europe: baseContext.europe,
      asia: baseContext.asia,
      americaWeight: baseContext.americaWeight,
      europeWeight: baseContext.europeWeight,
      asiaWeight: baseContext.asiaWeight,
      weightSource: baseContext.weightSource,
      weightConfidence: baseContext.weightConfidence,
      marketUniverseStatus: universeStatus,
      advancingPercentage: baseContext.advancingPercentage,
      decliningPercentage: baseContext.decliningPercentage,
      sentiment: baseContext.sentiment,
      summary: baseContext.summary,
    );
  }

  RegionalMarketWeights _resolveRegionalWeights(
    List<MarketUniverseAsset> universe, {
    required bool enforceBackendReadiness,
    required MarketUniverseStatus universeStatus,
  }) {
    if (enforceBackendReadiness && !universeStatus.isWeightingReady) {
      return RegionalMarketWeights.baseline;
    }

    try {
      return regionalMarketWeightService.calculate(universe);
    } on StateError {
      return RegionalMarketWeights.baseline;
    }
  }

  void _validateRegionalWeights(
    RegionalMarketWeights weights,
  ) {
    if (!weights.isValid) {
      throw StateError(
        'Los pesos regionales no forman una distribución válida.',
      );
    }
  }
}
