import 'package:app/features/profile/models/user_preferences.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('richer personalization round-trips through Flutter model', () {
    final preferences = UserPreferences.fromJson({
      'riskTolerance': 'growth',
      'investmentHorizonYears': 15,
      'baseCurrency': 'eur',
      'objective': 'long_term_growth',
      'experienceLevel': 'intermediate',
      'liquidityNeed': 'low',
      'maxDrawdownTolerancePct': 30,
    });

    expect(preferences.baseCurrency, 'EUR');
    expect(preferences.experienceLevel, 'intermediate');
    expect(preferences.liquidityNeed, 'low');
    expect(preferences.maxDrawdownTolerancePct, 30);
    expect(preferences.toJson(), {
      'riskTolerance': 'growth',
      'investmentHorizonYears': 15,
      'baseCurrency': 'EUR',
      'objective': 'long_term_growth',
      'experienceLevel': 'intermediate',
      'liquidityNeed': 'low',
      'maxDrawdownTolerancePct': 30,
    });
  });

  test('legacy four-field profile remains compatible', () {
    final preferences = UserPreferences.fromJson({
      'riskTolerance': 'balanced',
      'investmentHorizonYears': 10,
      'baseCurrency': 'EUR',
      'objective': 'balanced_growth',
    });

    expect(preferences.experienceLevel, isNull);
    expect(preferences.liquidityNeed, isNull);
    expect(preferences.maxDrawdownTolerancePct, isNull);
    expect(preferences.toJson().containsKey('experienceLevel'), isFalse);
    expect(preferences.toJson().containsKey('liquidityNeed'), isFalse);
    expect(preferences.toJson().containsKey('maxDrawdownTolerancePct'), isFalse);
  });

  test('invalid richer personalization values fail closed', () {
    expect(
      () => UserPreferences.fromJson({
        'riskTolerance': 'balanced',
        'investmentHorizonYears': 10,
        'baseCurrency': 'EUR',
        'objective': 'balanced_growth',
        'experienceLevel': 'expert',
      }),
      throwsFormatException,
    );
    expect(
      () => const UserPreferences(
        riskTolerance: 'balanced',
        investmentHorizonYears: 10,
        baseCurrency: 'EUR',
        objective: 'balanced_growth',
        liquidityNeed: 'urgent',
      ).toJson(),
      throwsArgumentError,
    );
    expect(
      () => const UserPreferences(
        riskTolerance: 'balanced',
        investmentHorizonYears: 10,
        baseCurrency: 'EUR',
        objective: 'balanced_growth',
        maxDrawdownTolerancePct: 61,
      ).toJson(),
      throwsArgumentError,
    );
  });
}
