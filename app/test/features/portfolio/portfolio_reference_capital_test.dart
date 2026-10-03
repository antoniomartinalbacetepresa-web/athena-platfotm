import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/portfolio/models/portfolio.dart';
import 'package:app/features/portfolio/models/portfolio_position.dart';

void main() {
  Portfolio buildPortfolio({
    required double referenceCapital,
    required double invested,
  }) {
    return Portfolio(
      id: 'test',
      name: 'Test',
      initialCapital: referenceCapital,
      positions: [
        PortfolioPosition(
          symbol: 'TEST',
          companyName: 'Test Instrument',
          shares: 1,
          averagePrice: invested,
          currentPrice: invested,
        ),
      ],
      createdAt: DateTime.utc(2026, 9, 2),
    );
  }

  test('expone referencia restante cuando el coste invertido es inferior', () {
    final portfolio = buildPortfolio(
      referenceCapital: 1500,
      invested: 1000,
    );

    expect(portfolio.referenceCapitalRemaining, 500);
    expect(portfolio.referenceCapitalExcess, 0);
    expect(portfolio.isOverReferenceCapital, isFalse);
  });

  test('expone exceso y no lo oculta como cero no asignado', () {
    final portfolio = buildPortfolio(
      referenceCapital: 1500,
      invested: 5502,
    );

    expect(portfolio.referenceCapitalRemaining, 0);
    expect(portfolio.referenceCapitalExcess, 4002);
    expect(portfolio.isOverReferenceCapital, isTrue);
  });

  test('sin capital de referencia no inventa disponibilidad ni exceso', () {
    final portfolio = buildPortfolio(
      referenceCapital: 0,
      invested: 1000,
    );

    expect(portfolio.referenceCapitalRemaining, 0);
    expect(portfolio.referenceCapitalExcess, 0);
    expect(portfolio.isOverReferenceCapital, isFalse);
  });
}
