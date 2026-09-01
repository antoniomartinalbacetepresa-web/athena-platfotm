import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/data/config/market_provider_config.dart';

void main() {
  group('MarketProviderConfig', () {
    test(
      'una configuración habilitada con API key está configurada',
      () {
        const config = MarketProviderConfig(
          providerId: 'twelve_data',
          apiKey: 'test-key',
        );

        expect(config.isConfigured, isTrue);
      },
    );

    test(
      'una configuración sin API key no está configurada',
      () {
        const config = MarketProviderConfig(
          providerId: 'twelve_data',
        );

        expect(config.isConfigured, isFalse);
      },
    );

    test(
      'una API key vacía no se considera configurada',
      () {
        const config = MarketProviderConfig(
          providerId: 'twelve_data',
          apiKey: '   ',
        );

        expect(config.isConfigured, isFalse);
      },
    );

    test(
      'un proveedor deshabilitado no se considera configurado',
      () {
        const config = MarketProviderConfig(
          providerId: 'twelve_data',
          enabled: false,
          apiKey: 'test-key',
        );

        expect(config.isConfigured, isFalse);
      },
    );

    test(
      'copyWith modifica los valores solicitados y conserva los demás',
      () {
        const config = MarketProviderConfig(
          providerId: 'twelve_data',
          enabled: true,
          apiKey: 'test-key',
          baseUrl: 'https://example.com',
        );

        final updated = config.copyWith(
          enabled: false,
          baseUrl: 'https://other.example.com',
        );

        expect(updated.providerId, 'twelve_data');
        expect(updated.enabled, isFalse);
        expect(updated.apiKey, 'test-key');
        expect(
          updated.baseUrl,
          'https://other.example.com',
        );
        expect(updated.isConfigured, isFalse);
      },
    );
  });
}
