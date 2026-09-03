import 'dart:async';

import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/portfolio/models/portfolio_position.dart';
import 'package:app/features/portfolio/presentation/controllers/portfolio_current_valuation_controller.dart';
import 'package:app/features/portfolio/services/portfolio_current_valuation_service.dart';

PortfolioCurrentValuation _valuation(double currentValue) {
  return PortfolioCurrentValuation(
    baseCurrency: 'EUR',
    currentValueInBaseCurrency: currentValue,
    positionsValued: 1,
    fxEvidence: const [],
    historicalCostBasisInBaseCurrency: currentValue,
    latestMarketObservedAt: DateTime.utc(2026, 9, 3, 6),
    latestMarketRetrievedAt: DateTime.utc(2026, 9, 3, 6, 1),
    latestFxObservedAt: null,
    latestFxRetrievedAt: null,
  );
}

void main() {
  test('applies the latest valuation result', () async {
    final controller = PortfolioCurrentValuationController(
      loadValuation: ({required positions, required baseCurrency}) async {
        expect(baseCurrency, 'EUR');
        return _valuation(1250);
      },
    );

    await controller.load(
      positions: const <PortfolioPosition>[],
      baseCurrency: 'EUR',
    );

    expect(controller.isLoading, isFalse);
    expect(controller.error, isNull);
    expect(controller.valuation?.currentValueInBaseCurrency, 1250);
  });

  test('fails closed when valuation cannot be verified', () async {
    final controller = PortfolioCurrentValuationController(
      loadValuation: ({required positions, required baseCurrency}) async {
        throw StateError('missing FX evidence');
      },
    );

    await controller.load(
      positions: const <PortfolioPosition>[],
      baseCurrency: 'EUR',
    );

    expect(controller.isLoading, isFalse);
    expect(controller.valuation, isNull);
    expect(controller.error, isNotNull);
  });

  test('older async result cannot overwrite a newer valuation', () async {
    final first = Completer<PortfolioCurrentValuation>();
    final second = Completer<PortfolioCurrentValuation>();
    var calls = 0;

    final controller = PortfolioCurrentValuationController(
      loadValuation: ({required positions, required baseCurrency}) {
        calls++;
        return calls == 1 ? first.future : second.future;
      },
    );

    final firstLoad = controller.load(
      positions: const <PortfolioPosition>[],
      baseCurrency: 'EUR',
    );
    final secondLoad = controller.load(
      positions: const <PortfolioPosition>[],
      baseCurrency: 'EUR',
    );

    second.complete(_valuation(2000));
    await secondLoad;
    expect(controller.valuation?.currentValueInBaseCurrency, 2000);

    first.complete(_valuation(1000));
    await firstLoad;

    expect(controller.valuation?.currentValueInBaseCurrency, 2000);
    expect(controller.isLoading, isFalse);
  });

  test('clear invalidates an in-flight valuation', () async {
    final pending = Completer<PortfolioCurrentValuation>();
    final controller = PortfolioCurrentValuationController(
      loadValuation: ({required positions, required baseCurrency}) =>
          pending.future,
    );

    final load = controller.load(
      positions: const <PortfolioPosition>[],
      baseCurrency: 'EUR',
    );
    expect(controller.isLoading, isTrue);

    controller.clear();
    expect(controller.isLoading, isFalse);
    expect(controller.valuation, isNull);

    pending.complete(_valuation(999));
    await load;

    expect(controller.valuation, isNull);
    expect(controller.error, isNull);
  });

  test('dispose invalidates an in-flight valuation without notifying later', () async {
    final pending = Completer<PortfolioCurrentValuation>();
    final controller = PortfolioCurrentValuationController(
      loadValuation: ({required positions, required baseCurrency}) =>
          pending.future,
    );

    var notifications = 0;
    controller.addListener(() => notifications++);

    final load = controller.load(
      positions: const <PortfolioPosition>[],
      baseCurrency: 'EUR',
    );
    expect(notifications, 1);

    controller.dispose();
    pending.complete(_valuation(777));

    await expectLater(load, completes);
    expect(notifications, 1);
  });

  test('forService delegates to the validated valuation service', () async {
    final service = PortfolioCurrentValuationService(
      loadCurrentFxRate: ({
        required baseCurrency,
        required quoteCurrency,
      }) async {
        throw StateError('FX must not be requested for an empty portfolio');
      },
    );
    final controller = PortfolioCurrentValuationController.forService(service);

    await controller.load(
      positions: const <PortfolioPosition>[],
      baseCurrency: 'EUR',
    );

    expect(controller.error, isNull);
    expect(controller.valuation?.currentValueInBaseCurrency, 0);
    expect(controller.valuation?.positionsValued, 0);
  });
}
