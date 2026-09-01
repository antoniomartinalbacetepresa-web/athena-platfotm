import '../financial/financial_data_provider.dart';
import '../providers/market_data_provider.dart';

/// Registro central de proveedores de datos de ATHENA TYCHE.
///
/// Mantiene desacoplado el dominio de mercado de proveedores concretos.
///
/// El registro conoce qué proveedores están disponibles, pero no ejecuta
/// peticiones ni captura errores de red.
///
/// También permite resolver proveedores según una lista explícita de
/// prioridades. Esto hace posible definir estrategias como:
///
/// athena_backend -> twelve_data -> mock_market
///
/// sin introducir dependencias concretas en las capas superiores.
///
/// IMPORTANTE:
///
/// Resolver una prioridad no significa ocultar errores de un proveedor.
/// Esta clase únicamente selecciona proveedores registrados.
///
/// La política de reintentos, fallback por fallo real, calidad de datos
/// y trazabilidad pertenece a una capa diferente.
class MarketProviderRegistry {
  final List<MarketDataProvider> marketProviders;
  final List<FinancialDataProvider> financialProviders;

  const MarketProviderRegistry({
    this.marketProviders = const [],
    this.financialProviders = const [],
  });

  /// Devuelve el proveedor de mercado identificado por [providerId].
  ///
  /// Devuelve null cuando no existe ningún proveedor registrado con
  /// ese identificador.
  MarketDataProvider? getMarketProvider(String providerId) {
    for (final provider in marketProviders) {
      if (provider.providerId == providerId) {
        return provider;
      }
    }

    return null;
  }

  /// Devuelve el proveedor financiero identificado por [providerId].
  ///
  /// Devuelve null cuando no existe ningún proveedor registrado con
  /// ese identificador.
  FinancialDataProvider? getFinancialProvider(String providerId) {
    for (final provider in financialProviders) {
      if (provider.providerId == providerId) {
        return provider;
      }
    }

    return null;
  }

  /// Devuelve true cuando existe un proveedor de mercado con [providerId].
  bool hasMarketProvider(String providerId) {
    return getMarketProvider(providerId) != null;
  }

  /// Devuelve true cuando existe un proveedor financiero con [providerId].
  bool hasFinancialProvider(String providerId) {
    return getFinancialProvider(providerId) != null;
  }

  /// Resuelve el primer proveedor de mercado registrado siguiendo
  /// exactamente el orden de [preferredProviderIds].
  ///
  /// Ejemplo:
  ///
  /// [
  ///   'athena_backend',
  ///   'twelve_data',
  ///   'mock_market',
  /// ]
  ///
  /// Si athena_backend no está registrado pero twelve_data sí,
  /// se devolverá twelve_data.
  ///
  /// Devuelve null cuando ninguno de los proveedores preferidos
  /// está registrado.
  MarketDataProvider? resolveMarketProvider(
    Iterable<String> preferredProviderIds,
  ) {
    for (final providerId in preferredProviderIds) {
      final provider = getMarketProvider(providerId);

      if (provider != null) {
        return provider;
      }
    }

    return null;
  }

  /// Resuelve el primer proveedor financiero registrado siguiendo
  /// exactamente el orden de [preferredProviderIds].
  ///
  /// Devuelve null cuando ninguno de los proveedores preferidos
  /// está registrado.
  FinancialDataProvider? resolveFinancialProvider(
    Iterable<String> preferredProviderIds,
  ) {
    for (final providerId in preferredProviderIds) {
      final provider = getFinancialProvider(providerId);

      if (provider != null) {
        return provider;
      }
    }

    return null;
  }

  /// Identificadores de todos los proveedores de mercado registrados,
  /// conservando el orden en el que fueron añadidos.
  List<String> get marketProviderIds {
    return marketProviders
        .map((provider) => provider.providerId)
        .toList(growable: false);
  }

  /// Identificadores de todos los proveedores financieros registrados,
  /// conservando el orden en el que fueron añadidos.
  List<String> get financialProviderIds {
    return financialProviders
        .map((provider) => provider.providerId)
        .toList(growable: false);
  }
}
