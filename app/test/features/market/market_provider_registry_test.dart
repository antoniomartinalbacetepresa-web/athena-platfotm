import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/data/financial/financial_data.dart';
import 'package:app/features/market/data/financial/financial_data_provider.dart';
import 'package:app/features/market/data/financial/mock_financial_data_provider.dart';
import 'package:app/features/market/data/models/market_data_point.dart';
import 'package:app/features/market/data/providers/market_data_provider.dart';
import 'package:app/features/market/data/registry/market_provider_registry.dart';

class _FakeMarketDataProvider implements MarketDataProvider {
  final String id;

  const _FakeMarketDataProvider({this.id = 'fake_market'});

  @override
  String get providerId => id;

  @override
  Future<MarketDataPoint?> getQuote(String symbol) async {
    return null;
  }

  @override
  Future<List<MarketDataPoint>> getHistoricalData({
    required String symbol,
    DateTime? from,
    DateTime? to,
  }) async {
    return [];
  }
}

class _FakeFinancialDataProvider implements FinancialDataProvider {
  final String id;

  const _FakeFinancialDataProvider({this.id = 'fake_financial'});

  @override
  String get providerId => id;

  @override
  Future<FinancialData?> getFinancialData({required String symbol}) async {
    return null;
  }
}

void main() {
  group('MarketProviderRegistry', () {
    test('registra y recupera un proveedor de mercado', () {
      const provider = _FakeMarketDataProvider();

      final registry = MarketProviderRegistry(marketProviders: [provider]);

      expect(registry.getMarketProvider('fake_market'), same(provider));

      expect(registry.hasMarketProvider('fake_market'), isTrue);
    });

    test('devuelve null para un proveedor de mercado inexistente', () {
      const registry = MarketProviderRegistry();

      expect(registry.getMarketProvider('unknown'), isNull);

      expect(registry.hasMarketProvider('unknown'), isFalse);
    });

    test('registra y recupera un proveedor financiero', () {
      final provider = MockFinancialDataProvider();

      final registry = MarketProviderRegistry(financialProviders: [provider]);

      expect(registry.getFinancialProvider('mock_financial'), same(provider));

      expect(registry.hasFinancialProvider('mock_financial'), isTrue);
    });

    test('devuelve null para un proveedor financiero inexistente', () {
      const registry = MarketProviderRegistry();

      expect(registry.getFinancialProvider('unknown'), isNull);

      expect(registry.hasFinancialProvider('unknown'), isFalse);
    });

    test('mantiene separados los proveedores de mercado y financieros', () {
      const marketProvider = _FakeMarketDataProvider();

      const financialProvider = _FakeFinancialDataProvider();

      final registry = MarketProviderRegistry(
        marketProviders: [marketProvider],
        financialProviders: [financialProvider],
      );

      expect(registry.getMarketProvider('fake_market'), same(marketProvider));

      expect(
        registry.getFinancialProvider('fake_financial'),
        same(financialProvider),
      );

      expect(registry.getMarketProvider('fake_financial'), isNull);

      expect(registry.getFinancialProvider('fake_market'), isNull);
    });

    test(
      'resuelve el primer proveedor de mercado disponible según prioridad',
      () {
        const backend = _FakeMarketDataProvider(id: 'athena_backend');

        const twelveData = _FakeMarketDataProvider(id: 'twelve_data');

        final registry = MarketProviderRegistry(
          marketProviders: [twelveData, backend],
        );

        final resolved = registry.resolveMarketProvider(const [
          'athena_backend',
          'twelve_data',
          'mock_market',
        ]);

        expect(resolved, same(backend));
      },
    );

    test(
      'continúa la prioridad cuando el primer proveedor no está registrado',
      () {
        const twelveData = _FakeMarketDataProvider(id: 'twelve_data');

        const mock = _FakeMarketDataProvider(id: 'mock_market');

        final registry = MarketProviderRegistry(
          marketProviders: [twelveData, mock],
        );

        final resolved = registry.resolveMarketProvider(const [
          'athena_backend',
          'twelve_data',
          'mock_market',
        ]);

        expect(resolved, same(twelveData));
      },
    );

    test(
      'devuelve null si ningún proveedor de mercado preferido está registrado',
      () {
        const registry = MarketProviderRegistry(
          marketProviders: [_FakeMarketDataProvider(id: 'other_market')],
        );

        final resolved = registry.resolveMarketProvider(const [
          'athena_backend',
          'twelve_data',
          'mock_market',
        ]);

        expect(resolved, isNull);
      },
    );

    test(
      'resuelve el primer proveedor financiero disponible según prioridad',
      () {
        const backendFinancial = _FakeFinancialDataProvider(
          id: 'athena_backend_financial',
        );

        const alphaVantage = _FakeFinancialDataProvider(id: 'alpha_vantage');

        final registry = MarketProviderRegistry(
          financialProviders: [alphaVantage, backendFinancial],
        );

        final resolved = registry.resolveFinancialProvider(const [
          'athena_backend_financial',
          'alpha_vantage',
          'mock_financial',
        ]);

        expect(resolved, same(backendFinancial));
      },
    );

    test('expone los identificadores de mercado conservando el orden', () {
      const registry = MarketProviderRegistry(
        marketProviders: [
          _FakeMarketDataProvider(id: 'athena_backend'),
          _FakeMarketDataProvider(id: 'twelve_data'),
          _FakeMarketDataProvider(id: 'mock_market'),
        ],
      );

      expect(registry.marketProviderIds, const [
        'athena_backend',
        'twelve_data',
        'mock_market',
      ]);
    });

    test('expone los identificadores financieros conservando el orden', () {
      const registry = MarketProviderRegistry(
        financialProviders: [
          _FakeFinancialDataProvider(id: 'athena_backend_financial'),
          _FakeFinancialDataProvider(id: 'alpha_vantage'),
          _FakeFinancialDataProvider(id: 'mock_financial'),
        ],
      );

      expect(registry.financialProviderIds, const [
        'athena_backend_financial',
        'alpha_vantage',
        'mock_financial',
      ]);
    });
  });
}
