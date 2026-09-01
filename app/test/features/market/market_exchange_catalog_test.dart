import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/models/market_exchange_catalog.dart';
import 'package:app/features/market/models/market_instrument_type.dart';
import 'package:app/features/market/models/market_universe_asset.dart';
import 'package:app/features/market/services/market_universe_normalizer.dart';

void main() {
  group('MarketExchangeCatalog', () {
    test('encuentra mercados principales por código Yahoo', () {
      final nyse =
          MarketExchangeCatalog.findByYahooCode('NYQ');

      final london =
          MarketExchangeCatalog.findByYahooCode('LSE');

      final tokyo =
          MarketExchangeCatalog.findByYahooCode('JPX');

      final hongKong =
          MarketExchangeCatalog.findByYahooCode('HKG');

      expect(nyse, isNotNull);
      expect(london, isNotNull);
      expect(tokyo, isNotNull);
      expect(hongKong, isNotNull);

      expect(nyse!.countryCode, 'US');
      expect(london!.countryCode, 'GB');
      expect(tokyo!.countryCode, 'JP');
      expect(hongKong!.countryCode, 'HK');
    });

    test('puede obtener mercados por región', () {
      final europe =
          MarketExchangeCatalog.byRegion('europe');

      final asia =
          MarketExchangeCatalog.byRegion('asia');

      final america =
          MarketExchangeCatalog.byRegion('america');

      expect(europe, isNotEmpty);
      expect(asia, isNotEmpty);
      expect(america, isNotEmpty);
    });

    test('puede obtener mercados por país', () {
      final japan =
          MarketExchangeCatalog.byCountry('JP');

      final spain =
          MarketExchangeCatalog.byCountry('ES');

      expect(japan, isNotEmpty);
      expect(spain, isNotEmpty);

      expect(
        japan.any((exchange) => exchange.yahooCode == 'JPX'),
        isTrue,
      );

      expect(
        spain.any((exchange) => exchange.yahooCode == 'MCE'),
        isTrue,
      );
    });
  });

  group('MarketUniverseAsset', () {
    test('distingue listings aunque pertenezcan al mismo emisor', () {
      const us = MarketUniverseAsset(
        symbol: 'NVDA',
        companyName: 'NVIDIA Corporation',
        exchangeShortName: 'NMS',
        issuerId: 'nvidia',
      );

      const canada = MarketUniverseAsset(
        symbol: 'NVDA.TO',
        companyName: 'NVIDIA CDR',
        exchangeShortName: 'TOR',
        issuerId: 'nvidia',
      );

      expect(us.issuerKey, canada.issuerKey);
      expect(us.listingKey, isNot(canada.listingKey));
    });
  });

  group('MarketUniverseNormalizer', () {
    const normalizer = MarketUniverseNormalizer();

    test('asigna país y región a partir del exchange Yahoo', () {
      const asset = MarketUniverseAsset(
        symbol: 'NVDA',
        companyName: 'NVIDIA Corporation',
        exchangeShortName: 'NMS',
      );

      final normalized =
          normalizer.normalizeAsset(asset);

      expect(normalized.country, 'US');
      expect(normalized.regionKey, 'america');
    });

    test('no fusiona listados diferentes', () {
      const assets = [
        MarketUniverseAsset(
          symbol: 'NVDA',
          companyName: 'NVIDIA Corporation',
          exchangeShortName: 'NMS',
          issuerId: 'nvidia',
        ),
        MarketUniverseAsset(
          symbol: 'NVDA.TO',
          companyName: 'NVIDIA CDR',
          exchangeShortName: 'TOR',
          issuerId: 'nvidia',
        ),
      ];

      final normalized =
          normalizer.normalize(assets);

      expect(normalized.length, 2);
    });

    test('clasifica CDR', () {
      final type = normalizer.inferInstrumentType(
        symbol: 'NVDA.TO',
        companyName: 'NVIDIA CDR',
      );

      expect(type, MarketInstrumentType.cdr);
    });

    test('clasifica ADR', () {
      final type = normalizer.inferInstrumentType(
        symbol: 'XYZ',
        companyName: 'Example ADR',
      );

      expect(type, MarketInstrumentType.adr);
    });

    test('clasifica ETF cuando aparece explícitamente', () {
      final type = normalizer.inferInstrumentType(
        symbol: 'TEST',
        companyName: 'Example ETF',
      );

      expect(type, MarketInstrumentType.etf);
    });
  });
}
