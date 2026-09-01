import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/models/market_universe_asset.dart';

void main() {
  test(
    'MarketUniverseAsset almacena correctamente los datos del activo',
    () {
      const asset = MarketUniverseAsset(
        symbol: 'AAPL',
        companyName: 'Apple Inc.',
        marketCap: 3.0e12,
        country: 'United States',
        exchange: 'NASDAQ Global Select Market',
        exchangeShortName: 'NASDAQ',
        sector: 'Technology',
        industry: 'Consumer Electronics',
      );

      expect(asset.symbol, 'AAPL');
      expect(asset.companyName, 'Apple Inc.');
      expect(asset.marketCap, 3.0e12);
      expect(asset.country, 'United States');
      expect(asset.exchange, 'NASDAQ Global Select Market');
      expect(asset.exchangeShortName, 'NASDAQ');
      expect(asset.sector, 'Technology');
      expect(asset.industry, 'Consumer Electronics');
    },
  );

  test(
    'MarketUniverseAsset permite campos opcionales vacíos',
    () {
      const asset = MarketUniverseAsset(
        symbol: 'XYZ',
        companyName: 'Example Company',
      );

      expect(asset.symbol, 'XYZ');
      expect(asset.companyName, 'Example Company');
      expect(asset.marketCap, isNull);
      expect(asset.country, isNull);
      expect(asset.exchange, isNull);
      expect(asset.exchangeShortName, isNull);
      expect(asset.sector, isNull);
      expect(asset.industry, isNull);
    },
  );

  test(
    'MarketUniverseAsset copyWith conserva los valores no modificados',
    () {
      const asset = MarketUniverseAsset(
        symbol: 'AAPL',
        companyName: 'Apple Inc.',
        marketCap: 3.0e12,
        country: 'United States',
        exchangeShortName: 'NASDAQ',
        sector: 'Technology',
        industry: 'Consumer Electronics',
      );

      final updated = asset.copyWith(
        marketCap: 3.1e12,
      );

      expect(updated.symbol, 'AAPL');
      expect(updated.companyName, 'Apple Inc.');
      expect(updated.marketCap, 3.1e12);
      expect(updated.country, 'United States');
      expect(updated.exchangeShortName, 'NASDAQ');
      expect(updated.sector, 'Technology');
      expect(updated.industry, 'Consumer Electronics');
    },
  );
}