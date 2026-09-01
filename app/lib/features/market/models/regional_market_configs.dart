import 'market_region.dart';
import 'regional_market_config.dart';

/// Configuraciones regionales utilizadas por ATHENA TYCHE.
///
/// IMPORTANTE:
/// Esta clase NO contiene pesos regionales.
///
/// Los pesos 50/30/20 que se utilizaron durante el desarrollo
/// eran provisionales y no forman parte de la arquitectura definitiva.
///
/// El peso real de cada región deberá calcularse dinámicamente
/// a partir de la capitalización del universo de mercado analizado.
class RegionalMarketConfigs {
  const RegionalMarketConfigs._();

  /// Configuración de América.
  static const america = RegionalMarketConfig(
    region: MarketRegion.america,
    displayName: 'América',
    benchmarkSymbols: [
      'SPY',
      'QQQ',
      'DIA',
    ],
  );

  /// Configuración de Europa.
  static const europe = RegionalMarketConfig(
    region: MarketRegion.europe,
    displayName: 'Europa',
    benchmarkSymbols: [
      'VGK',
      'FEZ',
    ],
  );

  /// Configuración de Asia.
  static const asia = RegionalMarketConfig(
    region: MarketRegion.asia,
    displayName: 'Asia',
    benchmarkSymbols: [
      'EWJ',
      'FXI',
      'EWH',
    ],
  );

  /// Todas las regiones utilizadas por ATHENA TYCHE.
  static const all = <RegionalMarketConfig>[
    america,
    europe,
    asia,
  ];
}