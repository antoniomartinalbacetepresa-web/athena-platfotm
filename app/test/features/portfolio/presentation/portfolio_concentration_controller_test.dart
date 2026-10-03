import 'dart:async';

import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/portfolio/models/portfolio_concentration_snapshot.dart';
import 'package:app/features/portfolio/models/portfolio_position.dart';
import 'package:app/features/portfolio/presentation/controllers/portfolio_concentration_controller.dart';

PortfolioPosition _position(String symbol) => PortfolioPosition(
      symbol: symbol,
      companyName: '$symbol Company',
      shares: 1,
      averagePrice: 100,
      currentPrice: 100,
    );

PortfolioConcentrationSnapshot _snapshot(String symbol) =>
    PortfolioConcentrationSnapshot(
      baseCurrency: 'EUR',
      totalCurrentValue: 100,
      positions: [
        PortfolioConcentrationPosition(
          symbol: symbol,
          currentValueInBaseCurrency: 100,
          weight: 1,
        ),
      ],
      concentrationIndex: 1,
      effectivePositionCount: 1,
      largestPositionSymbol: symbol,
      largestPositionWeight: 1,
    );

void main() {
  test('load exposes a verified concentration snapshot', () async {
    final controller = PortfolioConcentrationController(
      loadConcentration: ({required positions, required baseCurrency}) async {
        expect(baseCurrency, 'EUR');
        expect(positions.single.symbol, 'AAPL');
        return _snapshot('AAPL');
      },
    );

    await controller.load(positions: [_position('AAPL')]);

    expect(controller.isLoading, isFalse);
    expect(controller.error, isNull);
    expect(controller.snapshot?.largestPositionSymbol, 'AAPL');
    expect(controller.snapshot?.correlationAvailable, isFalse);
    expect(controller.snapshot?.productionEligible, isFalse);
  });

  test('load fails closed when concentration cannot be verified', () async {
    final controller = PortfolioConcentrationController(
      loadConcentration: ({required positions, required baseCurrency}) async {
        throw StateError('missing verified valuation');
      },
    );

    await controller.load(positions: [_position('AAPL')]);

    expect(controller.snapshot, isNull);
    expect(controller.isLoading, isFalse);
    expect(
      controller.error,
      'No se pudo calcular una concentración verificable de la cartera.',
    );
  });

  test('empty portfolio clears state without calling loader', () async {
    var calls = 0;
    final controller = PortfolioConcentrationController(
      loadConcentration: ({required positions, required baseCurrency}) async {
        calls++;
        return _snapshot('AAPL');
      },
    );

    await controller.load(positions: [_position('AAPL')]);
    await controller.load(positions: const []);

    expect(calls, 1);
    expect(controller.snapshot, isNull);
    expect(controller.error, isNull);
    expect(controller.isLoading, isFalse);
  });

  test('stale async result cannot overwrite newer portfolio state', () async {
    final first = Completer<PortfolioConcentrationSnapshot>();
    final second = Completer<PortfolioConcentrationSnapshot>();
    var calls = 0;
    final controller = PortfolioConcentrationController(
      loadConcentration: ({required positions, required baseCurrency}) {
        calls++;
        return calls == 1 ? first.future : second.future;
      },
    );

    final firstLoad = controller.load(positions: [_position('OLD')]);
    final secondLoad = controller.load(positions: [_position('NEW')]);
    second.complete(_snapshot('NEW'));
    await secondLoad;
    first.complete(_snapshot('OLD'));
    await firstLoad;

    expect(controller.snapshot?.largestPositionSymbol, 'NEW');
    expect(controller.error, isNull);
  });
}
