import '../models/global_market_context.dart';
import '../models/market_region.dart';
import '../models/market_universe_asset.dart';
import '../models/regional_market_context.dart';
import '../models/regional_market_weights.dart';
import '../repositories/market_universe_repository.dart';
import 'global_market_context_service.dart';
import 'regional_market_context_service.dart';
import 'regional_market_weight_service.dart';

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
/// El universo de mercado se utiliza para calcular pesos.
///
/// Cuando todavía no existe suficiente información de capitalización,
/// ATHENA TYCHE utiliza un baseline estructural provisional.
///
/// El origen de los pesos queda registrado en [GlobalMarketContext]
/// para no confundir una estimación provisional con un cálculo observado.
///
/// Este servicio no contiene lógica de inversión ni recomendaciones.
class GlobalMarketDataService {
  final RegionalMarketContextService regionalMarketContextService;
  final GlobalMarketContextService globalMarketContextService;
  final MarketUniverseRepository marketUniverseRepository;
  final RegionalMarketWeightService regionalMarketWeightService;

  const GlobalMarketDataService({
    required this.regionalMarketContextService,
    required this.globalMarketContextService,
    required this.marketUniverseRepository,
    required this.regionalMarketWeightService,
  });

  /// Construye el contexto global actual del mercado.
  ///
  /// Obtiene en paralelo:
  /// - el comportamiento de América, Europa y Asia;
  /// - el universo de activos utilizado para intentar calcular
  ///   los pesos regionales.
  ///
  /// Si el universo todavía no contiene capitalizaciones suficientes,
  /// utiliza temporalmente [RegionalMarketWeights.baseline].
  Future<GlobalMarketContext> getGlobalContext() async {
    const regions = [
      MarketRegion.america,
      MarketRegion.europe,
      MarketRegion.asia,
    ];

    final regionalContextsFuture = Future.wait(
      regions.map(
        (region) =>
            regionalMarketContextService.getRegionalContext(
          region: region,
        ),
      ),
    );

    final universeFuture =
        marketUniverseRepository.getUniverse();

    final regionalContexts = await regionalContextsFuture;
    final universe = await universeFuture;

    final contextsByRegion = <String, RegionalMarketContext>{
      for (final context in regionalContexts)
        context.region: context,
    };

    final america =
        contextsByRegion[MarketRegion.america.key];

    final europe =
        contextsByRegion[MarketRegion.europe.key];

    final asia =
        contextsByRegion[MarketRegion.asia.key];

    if (america == null ||
        europe == null ||
        asia == null) {
      throw StateError(
        'No se pudieron construir todos los contextos regionales.',
      );
    }

    final regionalWeights =
        _resolveRegionalWeights(universe);

    _validateRegionalWeights(regionalWeights);

    return globalMarketContextService.build(
      america: america,
      europe: europe,
      asia: asia,
      americaWeight: regionalWeights.america,
      europeWeight: regionalWeights.europe,
      asiaWeight: regionalWeights.asia,
      weightSource: regionalWeights.source,
      weightConfidence: regionalWeights.confidence,
    );
  }

  /// Intenta obtener pesos calculados utilizando el universo disponible.
  ///
  /// Si todavía no existe capitalización válida suficiente para efectuar
  /// el cálculo, utiliza el baseline estructural.
  ///
  /// No se capturan indiscriminadamente todas las excepciones:
  /// únicamente se utiliza el fallback ante [StateError].
  ///
  /// Otros errores continúan propagándose para evitar ocultar fallos reales.
  RegionalMarketWeights _resolveRegionalWeights(
    List<MarketUniverseAsset> universe,
  ) {
    try {
      return regionalMarketWeightService.calculate(
        universe,
      );
    } on StateError {
      return RegionalMarketWeights.baseline;
    }
  }

  /// Verifica que los pesos utilizados formen una distribución válida.
  void _validateRegionalWeights(
    RegionalMarketWeights weights,
  ) {
    if (!weights.isValid) {
      throw StateError(
        'Los pesos regionales no forman '
        'una distribución válida.',
      );
    }
  }
}