import 'market_provider_config.dart';

/// Configuración central de los proveedores de datos de ATHENA TYCHE.
///
/// Esta clase define qué proveedores están disponibles para cada
/// categoría de información. No contiene secretos reales.
class MarketProviderSettings {
  final MarketProviderConfig market;
  final MarketProviderConfig financial;

  const MarketProviderSettings({
    required this.market,
    required this.financial,
  });

  /// Configuración de desarrollo.
  ///
  /// No requiere ninguna clave API y permite mantener ATHENA TYCHE
  /// completamente operativa mientras las fuentes externas no estén
  /// configuradas.
  const MarketProviderSettings.development()
      : market = const MarketProviderConfig(
          providerId: 'mock_market',
        ),
        financial = const MarketProviderConfig(
          providerId: 'mock_financial',
        );

  /// Configuración para proveedores externos.
  ///
  /// Las claves se proporcionan desde una capa de configuración
  /// segura y no se almacenan dentro de este archivo.
  MarketProviderSettings.external({
    String? twelveDataApiKey,
    String? alphaVantageApiKey,
  })  : market = MarketProviderConfig(
          providerId: 'twelve_data',
          apiKey: twelveDataApiKey,
        ),
        financial = MarketProviderConfig(
          providerId: 'alpha_vantage',
          apiKey: alphaVantageApiKey,
        );

  bool get isMarketExternalConfigured => market.isConfigured;

  bool get isFinancialExternalConfigured =>
      financial.isConfigured;
}