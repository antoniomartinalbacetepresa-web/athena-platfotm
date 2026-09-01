import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/models/market_universe_asset.dart';
import 'package:app/features/market/services/regional_market_weight_service.dart';

void main() {
  const service = RegionalMarketWeightService();

  group('RegionalMarketWeightService', () {
    test('calcula pesos según capitalización de mercado', () {
      const assets = [
        MarketUniverseAsset(
          symbol: 'USA',
          companyName: 'USA Company',
          marketCap: 600,
          country: 'United States',
        ),
        MarketUniverseAsset(
          symbol: 'ESP',
          companyName: 'Spain Company',
          marketCap: 200,
          country: 'Spain',
        ),
        MarketUniverseAsset(
          symbol: 'JPN',
          companyName: 'Japan Company',
          marketCap: 200,
          country: 'Japan',
        ),
      ];

      final weights = service.calculate(assets);

      expect(weights.america, closeTo(0.6, 0.000001));
      expect(weights.europe, closeTo(0.2, 0.000001));
      expect(weights.asia, closeTo(0.2, 0.000001));
      expect(weights.total, closeTo(1.0, 0.000001));
      expect(weights.isValid, isTrue);
    });

    test('ignora activos sin market cap válida', () {
      const assets = [
        MarketUniverseAsset(
          symbol: 'USA',
          companyName: 'USA Company',
          marketCap: 100,
          country: 'United States',
        ),
        MarketUniverseAsset(
          symbol: 'NO_CAP',
          companyName: 'No Market Cap',
          marketCap: 0,
          country: 'Spain',
        ),
        MarketUniverseAsset(
          symbol: 'NULL_CAP',
          companyName: 'Null Market Cap',
          country: 'Japan',
        ),
      ];

      final weights = service.calculate(assets);

      expect(weights.america, closeTo(1.0, 0.000001));
      expect(weights.europe, closeTo(0.0, 0.000001));
      expect(weights.asia, closeTo(0.0, 0.000001));
    });

    test('ignora países que no pertenecen a las tres regiones', () {
      const assets = [
        MarketUniverseAsset(
          symbol: 'USA',
          companyName: 'USA Company',
          marketCap: 100,
          country: 'United States',
        ),
        MarketUniverseAsset(
          symbol: 'OTHER',
          companyName: 'Other Company',
          marketCap: 900,
          country: 'Australia',
        ),
      ];

      final weights = service.calculate(assets);

      expect(weights.america, closeTo(1.0, 0.000001));
      expect(weights.europe, closeTo(0.0, 0.000001));
      expect(weights.asia, closeTo(0.0, 0.000001));
    });

    test('falla cuando no existe capitalización regional válida', () {
      const assets = [
        MarketUniverseAsset(
          symbol: 'USA',
          companyName: 'USA Company',
          marketCap: 0,
          country: 'United States',
        ),
        MarketUniverseAsset(
          symbol: 'UNKNOWN',
          companyName: 'Unknown Company',
          marketCap: 100,
          country: 'Australia',
        ),
      ];

      expect(() => service.calculate(assets), throwsStateError);
    });
  });
}
