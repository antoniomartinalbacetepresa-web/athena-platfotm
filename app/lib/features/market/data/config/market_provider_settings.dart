import 'market_provider_config.dart';

/// Configuración central de proveedores de ATHENA TYCHE.
///
/// Flutter debe depender preferentemente del backend de ATHENA, no de APIs
/// financieras externas ni de secretos embebidos en el cliente.
class MarketProviderSettings {
  final MarketProviderConfig market;
  final MarketProviderConfig financial;

  const MarketProviderSettings({
    required this.market,
    required this.financial,
  });

  const MarketProviderSettings.development()
      : market = const MarketProviderConfig(
          providerId: 'mock_market',
        ),
        financial = const MarketProviderConfig(
          providerId: 'mock_financial',
        );

  MarketProviderSettings.athenaBackend({
    String baseUrl = 'http://127.0.0.1:8000',
  })  : market = MarketProviderConfig(
          providerId: 'athena_backend',
          baseUrl: baseUrl,
        ),
        financial = MarketProviderConfig(
          providerId: 'athena_backend',
          baseUrl: baseUrl,
        );

  bool get isMarketExternalConfigured => market.isConfigured;

  bool get isFinancialExternalConfigured => financial.isConfigured;
}
