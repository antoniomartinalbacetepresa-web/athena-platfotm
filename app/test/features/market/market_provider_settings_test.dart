import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/data/config/market_provider_settings.dart';

void main() {
  group('MarketProviderSettings', () {
    test(
      'development utiliza los proveedores mock',
      () {
        const settings = MarketProviderSettings.development();

        expect(settings.market.providerId, 'mock_market');
        expect(settings.financial.providerId, 'mock_financial');
        expect(settings.market.apiKey, isNull);
        expect(settings.financial.apiKey, isNull);
      },
    );

    test(
      'athenaBackend configura el backend real sin claves en Flutter',
      () {
        final settings = MarketProviderSettings.athenaBackend(
          baseUrl: 'http://127.0.0.1:8000',
        );

        expect(settings.market.providerId, 'athena_backend');
        expect(settings.financial.providerId, 'athena_backend');
        expect(settings.market.baseUrl, 'http://127.0.0.1:8000');
        expect(settings.financial.baseUrl, 'http://127.0.0.1:8000');
        expect(settings.market.apiKey, isNull);
        expect(settings.financial.apiKey, isNull);
        expect(settings.isMarketExternalConfigured, isTrue);
        expect(settings.isFinancialExternalConfigured, isTrue);
      },
    );

    test(
      'athenaBackend usa una URL local por defecto',
      () {
        final settings = MarketProviderSettings.athenaBackend();

        expect(settings.market.baseUrl, 'http://127.0.0.1:8000');
        expect(settings.financial.baseUrl, 'http://127.0.0.1:8000');
        expect(settings.isMarketExternalConfigured, isTrue);
      },
    );
  });
}
