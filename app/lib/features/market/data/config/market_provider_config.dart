/// Configuración de un proveedor externo de ATHENA TYCHE.
///
/// Esta clase no almacena secretos de forma persistente.
/// Las claves podrán ser proporcionadas posteriormente por una
/// capa de configuración segura o por el backend.
class MarketProviderConfig {
  final String providerId;
  final bool enabled;
  final String? apiKey;
  final String? baseUrl;

  const MarketProviderConfig({
    required this.providerId,
    this.enabled = true,
    this.apiKey,
    this.baseUrl,
  });

  /// Indica si el proveedor está configurado para utilizarse.
  ///
  /// Un proveedor sin clave no se considera listo para conexiones
  /// externas, aunque pueda estar habilitado conceptualmente.
  bool get isConfigured {
    if (!enabled) {
      return false;
    }

    final key = apiKey;

    return key != null && key.trim().isNotEmpty;
  }

  MarketProviderConfig copyWith({
    String? providerId,
    bool? enabled,
    String? apiKey,
    String? baseUrl,
  }) {
    return MarketProviderConfig(
      providerId: providerId ?? this.providerId,
      enabled: enabled ?? this.enabled,
      apiKey: apiKey ?? this.apiKey,
      baseUrl: baseUrl ?? this.baseUrl,
    );
  }
}