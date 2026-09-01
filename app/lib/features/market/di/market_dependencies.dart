import '../data/config/market_provider_settings.dart';
import '../data/datasources/athena_backend_market_universe_data_source.dart';
import '../data/providers/athena_backend_market_data_provider.dart';
import '../repositories/market_context_repository.dart';
import '../repositories/market_context_repository_impl.dart';
import '../repositories/market_repository.dart';
import '../repositories/market_repository_impl.dart';
import '../repositories/market_universe_repository.dart';
import '../repositories/market_universe_repository_impl.dart';
import '../repositories/mock_market_universe_repository.dart';
import '../services/athena_backend_market_service.dart';
import '../services/global_market_context_service.dart';
import '../services/global_market_data_service.dart';
import '../services/mock_market_context_service.dart';
import '../services/mock_market_service.dart';
import '../services/regional_market_context_service_impl.dart';
import '../services/regional_market_weight_service.dart';

/// Dependencias principales de la funcionalidad de mercado.
///
/// Por defecto la aplicación utiliza el backend de ATHENA TYCHE. Los mocks
/// sólo se utilizan cuando se solicita explícitamente la configuración de
/// desarrollo.
class MarketDependencies {
  static const String _defaultBackendUrl = String.fromEnvironment(
    'ATHENA_BACKEND_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );

  final MarketRepository repository;
  final MarketContextRepository marketContextRepository;
  final MarketUniverseRepository marketUniverseRepository;
  final GlobalMarketDataService globalMarketDataService;

  final AthenaBackendMarketDataProvider? _backendMarketProvider;
  final AthenaBackendMarketUniverseDataSource? _backendUniverseDataSource;

  const MarketDependencies({
    required this.repository,
    required this.marketContextRepository,
    required this.marketUniverseRepository,
    required this.globalMarketDataService,
    AthenaBackendMarketDataProvider? backendMarketProvider,
    AthenaBackendMarketUniverseDataSource? backendUniverseDataSource,
  })  : _backendMarketProvider = backendMarketProvider,
        _backendUniverseDataSource = backendUniverseDataSource;

  factory MarketDependencies.create({
    MarketProviderSettings? settings,
  }) {
    final effectiveSettings = settings ??
        MarketProviderSettings.athenaBackend(
          baseUrl: _defaultBackendUrl,
        );

    final regionalMarketWeightService = const RegionalMarketWeightService();

    late final MarketRepository marketRepository;
    late final MarketUniverseRepository marketUniverseRepository;
    AthenaBackendMarketDataProvider? backendMarketProvider;
    AthenaBackendMarketUniverseDataSource? backendUniverseDataSource;

    switch (effectiveSettings.market.providerId) {
      case 'mock_market':
        marketRepository = MarketRepositoryImpl(
          marketService: const MockMarketService(),
        );
        marketUniverseRepository = const MockMarketUniverseRepository();

      case 'athena_backend':
        final baseUrl = effectiveSettings.market.baseUrl?.trim();
        if (baseUrl == null || baseUrl.isEmpty) {
          throw StateError(
            'ATHENA_BACKEND_URL no está configurada para el proveedor real.',
          );
        }

        backendMarketProvider = AthenaBackendMarketDataProvider(
          baseUrl: baseUrl,
        );
        backendUniverseDataSource = AthenaBackendMarketUniverseDataSource(
          baseUrl: baseUrl,
        );

        marketRepository = MarketRepositoryImpl(
          marketService: AthenaBackendMarketService(
            provider: backendMarketProvider,
          ),
        );
        marketUniverseRepository = MarketUniverseRepositoryImpl(
          dataSource: backendUniverseDataSource,
        );

      default:
        throw UnsupportedError(
          'Proveedor de mercado no soportado en Flutter: '
          '${effectiveSettings.market.providerId}. '
          'Los proveedores externos deben conectarse desde el backend.',
        );
    }

    final marketContextRepository = MarketContextRepositoryImpl(
      marketContextService: const MockMarketContextService(),
    );

    final regionalMarketContextService = RegionalMarketContextServiceImpl(
      marketRepository: marketRepository,
    );

    const globalMarketContextService = GlobalMarketContextService();

    final globalMarketDataService = GlobalMarketDataService(
      regionalMarketContextService: regionalMarketContextService,
      globalMarketContextService: globalMarketContextService,
      marketUniverseRepository: marketUniverseRepository,
      regionalMarketWeightService: regionalMarketWeightService,
    );

    return MarketDependencies(
      repository: marketRepository,
      marketContextRepository: marketContextRepository,
      marketUniverseRepository: marketUniverseRepository,
      globalMarketDataService: globalMarketDataService,
      backendMarketProvider: backendMarketProvider,
      backendUniverseDataSource: backendUniverseDataSource,
    );
  }

  void dispose() {
    _backendMarketProvider?.dispose();
    _backendUniverseDataSource?.dispose();
  }
}
