/// Configuración de un proveedor de datos de ATHENA TYCHE.
///
/// Las claves de proveedores externos nunca deben residir en Flutter Web.
/// El proveedor recomendado para la aplicación es el backend de ATHENA,
/// que protege los secretos y normaliza las fuentes en el servidor.
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

  bool get isConfigured {
    if (!enabled) {
      return false;
    }

    if (providerId.startsWith('mock_')) {
      return true;
    }

    final url = baseUrl;
    if (providerId == 'athena_backend') {
      return url != null && url.trim().isNotEmpty;
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
