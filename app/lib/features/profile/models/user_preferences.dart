class UserPreferences {
  const UserPreferences({
    required this.riskTolerance,
    required this.investmentHorizonYears,
    required this.baseCurrency,
    required this.objective,
  });

  static const riskTolerances = <String>{
    'conservative',
    'balanced',
    'growth',
    'aggressive',
  };

  static const objectives = <String>{
    'capital_preservation',
    'income',
    'balanced_growth',
    'long_term_growth',
  };

  final String riskTolerance;
  final int investmentHorizonYears;
  final String baseCurrency;
  final String objective;

  factory UserPreferences.fromJson(Map<String, dynamic> json) {
    final risk = json['riskTolerance'];
    final horizon = json['investmentHorizonYears'];
    final currency = json['baseCurrency'];
    final objective = json['objective'];
    if (risk is! String || !riskTolerances.contains(risk)) {
      throw const FormatException('riskTolerance no válido.');
    }
    if (horizon is! int || horizon < 1 || horizon > 60) {
      throw const FormatException('investmentHorizonYears no válido.');
    }
    if (currency is! String ||
        !RegExp(r'^[A-Z]{3}$').hasMatch(currency.trim().toUpperCase())) {
      throw const FormatException('baseCurrency no válida.');
    }
    if (objective is! String || !objectives.contains(objective)) {
      throw const FormatException('objective no válido.');
    }
    return UserPreferences(
      riskTolerance: risk,
      investmentHorizonYears: horizon,
      baseCurrency: currency.trim().toUpperCase(),
      objective: objective,
    );
  }

  Map<String, dynamic> toJson() {
    final risk = riskTolerance.trim();
    final currency = baseCurrency.trim().toUpperCase();
    final targetObjective = objective.trim();
    if (!riskTolerances.contains(risk)) {
      throw ArgumentError.value(riskTolerance, 'riskTolerance');
    }
    if (investmentHorizonYears < 1 || investmentHorizonYears > 60) {
      throw ArgumentError.value(investmentHorizonYears, 'investmentHorizonYears');
    }
    if (!RegExp(r'^[A-Z]{3}$').hasMatch(currency)) {
      throw ArgumentError.value(baseCurrency, 'baseCurrency');
    }
    if (!objectives.contains(targetObjective)) {
      throw ArgumentError.value(objective, 'objective');
    }
    return {
      'riskTolerance': risk,
      'investmentHorizonYears': investmentHorizonYears,
      'baseCurrency': currency,
      'objective': targetObjective,
    };
  }
}
