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

        expect(settings.isMarketExternalConfigured, isFalse);
        expect(settings.isFinancialExternalConfigured, isFalse);
      },
    );

    test(
      'external configura Twelve Data y Alpha Vantage',
      () {
        final settings = MarketProviderSettings.external(
          twelveDataApiKey: 'twelve-test-key',
          alphaVantageApiKey: 'alpha-test-key',
        );

        expect(settings.market.providerId, 'twelve_data');
        expect(
          settings.financial.providerId,
          'alpha_vantage',
        );

        expect(settings.market.apiKey, 'twelve-test-key');
        expect(
          settings.financial.apiKey,
          'alpha-test-key',
        );

        expect(settings.isMarketExternalConfigured, isTrue);
        expect(
          settings.isFinancialExternalConfigured,
          isTrue,
        );
      },
    );

    test(
      'external sin claves no se considera configurado',
      () {
        final settings = MarketProviderSettings.external();

        expect(settings.market.providerId, 'twelve_data');
        expect(
          settings.financial.providerId,
          'alpha_vantage',
        );

        expect(settings.isMarketExternalConfigured, isFalse);
        expect(
          settings.isFinancialExternalConfigured,
          isFalse,
        );
      },
    );

    test(
      'external permite configurar una sola fuente',
      () {
        final settings = MarketProviderSettings.external(
          twelveDataApiKey: 'twelve-test-key',
        );

        expect(settings.isMarketExternalConfigured, isTrue);
        expect(
          settings.isFinancialExternalConfigured,
          isFalse,
        );
      },
    );

    test(
      'development no contiene claves API',
      () {
        const settings = MarketProviderSettings.development();

        expect(settings.market.apiKey, isNull);
        expect(settings.financial.apiKey, isNull);
      },
    );
  });
}
