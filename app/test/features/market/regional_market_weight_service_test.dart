import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/models/market_universe_asset.dart';
import 'package:app/features/market/services/regional_market_weight_service.dart';

void main() {
  group('RegionalMarketWeightService', () {
    const service = RegionalMarketWeightService();

    test(
      'calcula correctamente los pesos regionales a partir de la capitalización',
      () {
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

        expect(
          weights.america + weights.europe + weights.asia,
          closeTo(1.0, 0.000001),
        );
      },
    );

    test(
      'no asigna confianza total a una muestra pequeña aunque esté completa',
      () {
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

        expect(weights.confidence, greaterThan(0));
        expect(weights.confidence, lessThan(0.8));
      },
    );

    test(
      'penaliza cobertura incompleta del universo',
      () {
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
            marketCap: null,
            country: 'Spain',
          ),
          MarketUniverseAsset(
            symbol: 'JPN',
            companyName: 'Japan Company',
            marketCap: null,
            country: 'Japan',
          ),
        ];

        final weights = service.calculate(assets);

        expect(weights.confidence, lessThan(0.4));
      },
    );

    test(
      'ignora activos con marketCap nula o no positiva',
      () {
        const assets = [
          MarketUniverseAsset(
            symbol: 'USA',
            companyName: 'USA Company',
            marketCap: 600,
            country: 'United States',
          ),
          MarketUniverseAsset(
            symbol: 'NO_CAP',
            companyName: 'No Cap Company',
            marketCap: null,
            country: 'Spain',
          ),
          MarketUniverseAsset(
            symbol: 'ZERO',
            companyName: 'Zero Cap Company',
            marketCap: 0,
            country: 'Spain',
          ),
          MarketUniverseAsset(
            symbol: 'NEGATIVE',
            companyName: 'Negative Cap Company',
            marketCap: -100,
            country: 'Japan',
          ),
        ];

        final weights = service.calculate(assets);

        expect(weights.america, closeTo(1.0, 0.000001));
        expect(weights.europe, closeTo(0.0, 0.000001));
        expect(weights.asia, closeTo(0.0, 0.000001));
      },
    );

    test(
      'ignora activos cuyo país no pertenece a una región conocida',
      () {
        const assets = [
          MarketUniverseAsset(
            symbol: 'USA',
            companyName: 'USA Company',
            marketCap: 600,
            country: 'United States',
          ),
          MarketUniverseAsset(
            symbol: 'UNKNOWN',
            companyName: 'Unknown Company',
            marketCap: 400,
            country: 'Unknown Country',
          ),
        ];

        final weights = service.calculate(assets);

        expect(weights.america, closeTo(1.0, 0.000001));
        expect(weights.europe, closeTo(0.0, 0.000001));
        expect(weights.asia, closeTo(0.0, 0.000001));
      },
    );

    test(
      'reconoce países y alias relevantes de América',
      () {
        const assets = [
          MarketUniverseAsset(
            symbol: 'US',
            companyName: 'US Company',
            marketCap: 100,
            country: 'USA',
          ),
          MarketUniverseAsset(
            symbol: 'CA',
            companyName: 'Canada Company',
            marketCap: 100,
            country: 'Canada',
          ),
          MarketUniverseAsset(
            symbol: 'BR',
            companyName: 'Brazil Company',
            marketCap: 100,
            country: 'Brazil',
          ),
        ];

        final weights = service.calculate(assets);

        expect(weights.america, closeTo(1.0, 0.000001));
      },
    );

    test(
      'reconoce países relevantes de Europa',
      () {
        const assets = [
          MarketUniverseAsset(
            symbol: 'GB',
            companyName: 'UK Company',
            marketCap: 100,
            country: 'United Kingdom',
          ),
          MarketUniverseAsset(
            symbol: 'DE',
            companyName: 'Germany Company',
            marketCap: 100,
            country: 'Germany',
          ),
          MarketUniverseAsset(
            symbol: 'ES',
            companyName: 'Spain Company',
            marketCap: 100,
            country: 'Spain',
          ),
        ];

        final weights = service.calculate(assets);

        expect(weights.europe, closeTo(1.0, 0.000001));
      },
    );

    test(
      'reconoce países relevantes de Asia',
      () {
        const assets = [
          MarketUniverseAsset(
            symbol: 'JP',
            companyName: 'Japan Company',
            marketCap: 100,
            country: 'Japan',
          ),
          MarketUniverseAsset(
            symbol: 'CN',
            companyName: 'China Company',
            marketCap: 100,
            country: 'China',
          ),
          MarketUniverseAsset(
            symbol: 'TW',
            companyName: 'Taiwan Company',
            marketCap: 100,
            country: 'Taiwan',
          ),
        ];

        final weights = service.calculate(assets);

        expect(weights.asia, closeTo(1.0, 0.000001));
      },
    );

    test(
      'falla cuando no existe ninguna capitalización regional válida',
      () {
        const assets = [
          MarketUniverseAsset(
            symbol: 'UNKNOWN',
            companyName: 'Unknown Company',
            marketCap: 100,
            country: 'Unknown Country',
          ),
          MarketUniverseAsset(
            symbol: 'NO_CAP',
            companyName: 'No Cap Company',
            marketCap: null,
            country: 'United States',
          ),
        ];

        expect(
          () => service.calculate(assets),
          throwsStateError,
        );
      },
    );

    test(
      'ignora activos inválidos aunque tengan capitalización',
      () {
        const assets = [
          MarketUniverseAsset(
            symbol: '',
            companyName: 'Invalid Symbol',
            marketCap: 1000,
            country: 'United States',
          ),
          MarketUniverseAsset(
            symbol: 'VALID',
            companyName: 'Valid Company',
            marketCap: 100,
            country: 'Spain',
          ),
        ];

        final weights = service.calculate(assets);

        expect(weights.america, closeTo(0.0, 0.000001));
        expect(weights.europe, closeTo(1.0, 0.000001));
        expect(weights.asia, closeTo(0.0, 0.000001));
      },
    );
  });
}
