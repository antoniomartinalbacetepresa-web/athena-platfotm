import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/portfolio/models/portfolio.dart';

void main() {
  group('Portfolio reference capital currency', () {
    final createdAt = DateTime.utc(2026, 9, 6, 12);

    test('persists and restores explicit ISO currency', () {
      final portfolio = Portfolio(
        id: 'portfolio-1',
        name: 'Mi cartera',
        initialCapital: 10000,
        referenceCapitalCurrency: 'USD',
        positions: const [],
        createdAt: createdAt,
      );

      final encoded = portfolio.toMap();
      expect(encoded['referenceCapitalCurrency'], 'USD');

      final restored = Portfolio.fromMap(encoded);
      expect(restored.referenceCapitalCurrency, 'USD');
      expect(restored.initialCapital, 10000);
    });

    test('normalizes persisted currency casing without inferring from positions', () {
      final restored = Portfolio.fromMap({
        'id': 'portfolio-2',
        'name': 'Mi cartera',
        'initialCapital': 5000,
        'referenceCapitalCurrency': ' gbp ',
        'positions': <Object?>[],
        'createdAt': createdAt.toIso8601String(),
      });

      expect(restored.referenceCapitalCurrency, 'GBP');
    });

    test('legacy records preserve the historical EUR interpretation', () {
      final restored = Portfolio.fromMap({
        'id': 'legacy',
        'name': 'Mi cartera',
        'initialCapital': 2500,
        'positions': <Object?>[],
        'createdAt': createdAt.toIso8601String(),
      });

      expect(restored.referenceCapitalCurrency, 'EUR');
    });

    test('invalid persisted currency fails closed', () {
      expect(
        () => Portfolio.fromMap({
          'id': 'invalid',
          'name': 'Mi cartera',
          'initialCapital': 2500,
          'referenceCapitalCurrency': 'EURO',
          'positions': <Object?>[],
          'createdAt': createdAt.toIso8601String(),
        }),
        throwsFormatException,
      );
    });

    test('copyWith preserves currency unless explicitly changed', () {
      final portfolio = Portfolio(
        id: 'portfolio-3',
        name: 'Mi cartera',
        initialCapital: 10000,
        referenceCapitalCurrency: 'EUR',
        positions: const [],
        createdAt: createdAt,
      );

      expect(
        portfolio.copyWith(initialCapital: 12000).referenceCapitalCurrency,
        'EUR',
      );
      expect(
        portfolio.copyWith(referenceCapitalCurrency: 'CHF')
            .referenceCapitalCurrency,
        'CHF',
      );
    });
  });
}
