import 'market_region.dart';

/// Configuración de una región utilizada por ATHENA TYCHE.
///
/// Esta clase define el universo de referencia de una región.
/// No contiene pesos globales.
///
/// Los pesos regionales NO deben estar codificados aquí.
/// Deben calcularse dinámicamente a partir de los datos reales
/// del universo de mercado utilizado por ATHENA TYCHE.
class RegionalMarketConfig {
  /// Región representada por esta configuración.
  final MarketRegion region;

  /// Nombre mostrado al usuario.
  final String displayName;

  /// Símbolos utilizados como benchmarks regionales.
  ///
  /// Estos símbolos sirven para medir el comportamiento de la región.
  /// No representan por sí mismos el peso real de la región
  /// dentro del mercado mundial.
  final List<String> benchmarkSymbols;

  const RegionalMarketConfig({
    required this.region,
    required this.displayName,
    required this.benchmarkSymbols,
  });
}