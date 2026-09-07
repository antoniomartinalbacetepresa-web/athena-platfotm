import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/recommendations/models/recommendation_production_state.dart';

const _recommendationFingerprint =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const _allocationFingerprint =
    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
const _economicFingerprint =
    'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc';

RecommendationProductionRecommendation _recommendation({
  DateTime? asOf,
  DateTime? authorizedAt,
}) {
  return RecommendationProductionRecommendation(
    instrumentId: 7,
    symbol: 'AAPL',
    action: 'buy',
    policyState: 'flat',
    asOf: asOf ?? DateTime.utc(2026, 9, 1, 11),
    authorizedAt: authorizedAt ?? DateTime.utc(2026, 9, 1, 11, 30),
    authorizationFingerprint: _recommendationFingerprint,
    economicContractFingerprint: _economicFingerprint,
  );
}

RecommendationProductionAllocation _allocation({
  int instrumentId = 7,
  DateTime? asOf,
  DateTime? authorizedAt,
  String recommendationFingerprint = _recommendationFingerprint,
  double referenceCapital = 10000,
  double targetAmount = 1500,
  double deltaAmount = 1500,
}) {
  return RecommendationProductionAllocation(
    instrumentId: instrumentId,
    symbol: 'AAPL',
    action: 'buy',
    asOf: asOf ?? DateTime.utc(2026, 9, 1, 11),
    authorizedAt: authorizedAt ?? DateTime.utc(2026, 9, 1, 11, 45),
    authorizationFingerprint: _allocationFingerprint,
    recommendationAuthorizationFingerprint: recommendationFingerprint,
    economicContractFingerprint: _economicFingerprint,
    baseCurrency: 'EUR',
    referenceCapital: referenceCapital,
    targetAmountInBaseCurrency: targetAmount,
    deltaAmountInBaseCurrency: deltaAmount,
  );
}

RecommendationProductionState _state({
  RecommendationProductionRecommendation? recommendation,
  RecommendationProductionAllocation? allocation,
}) {
  final effectiveRecommendation = recommendation ?? _recommendation();
  final effectiveAllocation = allocation ?? _allocation();
  return RecommendationProductionState(
    asOf: DateTime.utc(2026, 9, 1, 12),
    recommendation: effectiveRecommendation,
    allocation: effectiveAllocation,
    productionRecommendationAvailable: true,
    productionAllocationAvailable: true,
    automaticTrading: false,
    readOnly: true,
  );
}

void main() {
  test('acepta sólo recomendación y allocation productivos coherentes', () {
    expect(_state().isSafe, isTrue);
  });

  test('rechaza allocation recompuesto con otro instrumento o fingerprint', () {
    expect(_state(allocation: _allocation(instrumentId: 8)).isSafe, isFalse);
    expect(
      _state(
        allocation: _allocation(
          recommendationFingerprint:
              'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
        ),
      ).isSafe,
      isFalse,
    );
  });

  test('rechaza allocation con cutoff PIT distinto o autorización anterior', () {
    expect(
      _state(
        allocation: _allocation(asOf: DateTime.utc(2026, 9, 1, 10, 59)),
      ).isSafe,
      isFalse,
    );
    expect(
      _state(
        allocation: _allocation(authorizedAt: DateTime.utc(2026, 9, 1, 11, 20)),
      ).isSafe,
      isFalse,
    );
  });

  test('rechaza capital, target o delta no finitos', () {
    expect(
      _state(allocation: _allocation(referenceCapital: double.nan)).isSafe,
      isFalse,
    );
    expect(
      _state(allocation: _allocation(targetAmount: double.infinity)).isSafe,
      isFalse,
    );
    expect(
      _state(allocation: _allocation(deltaAmount: double.negativeInfinity)).isSafe,
      isFalse,
    );
  });

  test('rechaza autorización productiva posterior al cutoff visible', () {
    expect(
      _state(
        recommendation: _recommendation(
          authorizedAt: DateTime.utc(2026, 9, 1, 12, 1),
        ),
      ).isSafe,
      isFalse,
    );
  });
}
