import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/portfolio/models/portfolio_position.dart';

void main() {
  group('PortfolioPosition canonical identity persistence', () {
    PortfolioPosition position() => PortfolioPosition(
          symbol: 'AAPL',
          companyName: 'Apple Inc.',
          shares: 2,
          averagePrice: 200,
          currentPrice: 210,
          priceCurrency: 'USD',
          exchange: 'NASDAQ',
          databaseInstrumentId: 7,
          canonicalInstrumentId: 'AAPL@NASDAQ',
          canonicalIssuerId: 'issuer:apple',
          identitySourceProvider: 'yahoo_catalog',
          identityRetrievedAt: DateTime.utc(2026, 9, 4, 18),
          identityResolutionMethod: 'symbol_and_exchange_exact',
          identityExchangeVerified: true,
          identityRiskReady: true,
        );

    test('round-trips verified canonical identity and provenance', () {
      final restored = PortfolioPosition.fromMap(position().toMap());

      expect(restored.databaseInstrumentId, 7);
      expect(restored.canonicalInstrumentId, 'AAPL@NASDAQ');
      expect(restored.canonicalIssuerId, 'issuer:apple');
      expect(restored.identitySourceProvider, 'yahoo_catalog');
      expect(restored.identityRetrievedAt, DateTime.utc(2026, 9, 4, 18));
      expect(restored.identityResolutionMethod, 'symbol_and_exchange_exact');
      expect(restored.identityExchangeVerified, isTrue);
      expect(restored.identityRiskReady, isTrue);
      expect(restored.hasVerifiedCanonicalIdentity, isTrue);
    });

    test('legacy position remains readable but is not risk ready', () {
      final restored = PortfolioPosition.fromMap({
        'symbol': 'AAPL',
        'companyName': 'Apple Inc.',
        'shares': 1,
        'averagePrice': 100,
        'currentPrice': 101,
      });

      expect(restored.databaseInstrumentId, isNull);
      expect(restored.identityRiskReady, isFalse);
      expect(restored.hasVerifiedCanonicalIdentity, isFalse);
    });

    test('incomplete identity cannot become verified merely from booleans', () {
      final restored = PortfolioPosition.fromMap({
        'symbol': 'AAPL',
        'companyName': 'Apple Inc.',
        'shares': 1,
        'averagePrice': 100,
        'currentPrice': 101,
        'databaseInstrumentId': 7,
        'identityExchangeVerified': true,
        'identityRiskReady': true,
      });

      expect(restored.hasVerifiedCanonicalIdentity, isFalse);
    });
  });
}
