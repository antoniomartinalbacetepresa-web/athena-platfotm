import '../data/config/market_provider_settings.dart';
import '../repositories/market_context_repository.dart';
import '../repositories/market_context_repository_impl.dart';
import '../repositories/market_repository.dart';
import '../repositories/market_repository_impl.dart';
import '../repositories/market_universe_repository.dart';
import '../repositories/mock_market_universe_repository.dart';
import '../services/global_market_context_service.dart';
import '../services/global_market_data_service.dart';
import '../services/mock_market_context_service.dart';
import '../services/mock_market_service.dart';
import '../services/regional_market_context_service_impl.dart';
import '../services/regional_market_weight_service.dart';

/// Dependencias principales de la funcionalidad de mercado.
///
/// Esta configuración mantiene desacoplado el dominio de los proveedores
/// externos.
///
/// Las fuentes externas se configuran mediante [MarketProviderSettings].
/// Por defecto se utiliza configuración de desarrollo para mantener
/// ATHENA TYCHE operativa sin claves API.
class MarketDependencies {
  final MarketRepository repository;
  final MarketContextRepository marketContextRepository;
  final MarketUniverseRepository marketUniverseRepository;
  final GlobalMarketDataService globalMarketDataService;

  const MarketDependencies({
    required this.repository,
    required this.marketContextRepository,
    required this.marketUniverseRepository,
    required this.globalMarketDataService,
  });

  /// Construye las dependencias de mercado de ATHENA TYCHE.
  ///
  /// Cuando no se proporciona configuración se utiliza el modo desarrollo,
  /// que emplea proveedores mock y no necesita conexión externa.
  factory MarketDependencies.create({
    MarketProviderSettings? settings,
  }) {
    final effectiveSettings =
        settings ?? const MarketProviderSettings.development();

    final regionalMarketWeightService =
        const RegionalMarketWeightService();

    final marketRepository = MarketRepositoryImpl(
      marketService: const MockMarketService(),
    );

    final marketContextRepository = MarketContextRepositoryImpl(
      marketContextService: const MockMarketContextService(),
    );

    const marketUniverseRepository =
        MockMarketUniverseRepository();

    final regionalMarketContextService =
        RegionalMarketContextServiceImpl(
      marketRepository: marketRepository,
    );

    const globalMarketContextService =
        GlobalMarketContextService();

    final globalMarketDataService =
        GlobalMarketDataService(
      regionalMarketContextService:
          regionalMarketContextService,
      globalMarketContextService:
          globalMarketContextService,
      marketUniverseRepository:
          marketUniverseRepository,
      regionalMarketWeightService:
          regionalMarketWeightService,
    );

    // En esta fase la aplicación continúa utilizando los proveedores mock.
    //
    // La configuración externa se conserva para que la composición de
    // dependencias pueda evolucionar posteriormente hacia proveedores
    // reales sin modificar el dominio.
    //
    // No se utilizan claves API directamente desde esta capa.
    final _ = effectiveSettings;

    return MarketDependencies(
      repository: marketRepository,
      marketContextRepository: marketContextRepository,
      marketUniverseRepository: marketUniverseRepository,
      globalMarketDataService: globalMarketDataService,
    );
  }

  /// No existen recursos externos que liberar en la configuración actual.
  void dispose() {}
}