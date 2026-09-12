class UserPreferences {
  const UserPreferences({
    required this.riskTolerance,
    required this.investmentHorizonYears,
    required this.baseCurrency,
    required this.objective,
    this.experienceLevel,
    this.liquidityNeed,
    this.maxDrawdownTolerancePct,
    this.availableCapital,
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

  static const experienceLevels = <String>{
    'beginner',
    'intermediate',
    'advanced',
  };

  static const liquidityNeeds = <String>{
    'low',
    'medium',
    'high',
  };

  static const double maxAvailableCapital = 1000000000000;

  final String riskTolerance;
  final int investmentHorizonYears;
  final String baseCurrency;
  final String objective;
  final String? experienceLevel;
  final String? liquidityNeed;
  final int? maxDrawdownTolerancePct;
  final double? availableCapital;

  factory UserPreferences.fromJson(Map<String, dynamic> json) {
    final risk = json['riskTolerance'];
    final horizon = json['investmentHorizonYears'];
    final currency = json['baseCurrency'];
    final objective = json['objective'];
    final experience = json['experienceLevel'];
    final liquidity = json['liquidityNeed'];
    final drawdown = json['maxDrawdownTolerancePct'];
    final availableCapital = json['availableCapital'];
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
    if (experience != null &&
        (experience is! String || !experienceLevels.contains(experience))) {
      throw const FormatException('experienceLevel no válido.');
    }
    if (liquidity != null &&
        (liquidity is! String || !liquidityNeeds.contains(liquidity))) {
      throw const FormatException('liquidityNeed no válido.');
    }
    if (drawdown != null &&
        (drawdown is! int || drawdown < 5 || drawdown > 60)) {
      throw const FormatException('maxDrawdownTolerancePct no válido.');
    }
    if (availableCapital != null &&
        (availableCapital is! num ||
            !availableCapital.isFinite ||
            availableCapital < 0 ||
            availableCapital > maxAvailableCapital)) {
      throw const FormatException('availableCapital no válido.');
    }
    return UserPreferences(
      riskTolerance: risk,
      investmentHorizonYears: horizon,
      baseCurrency: currency.trim().toUpperCase(),
      objective: objective,
      experienceLevel: experience as String?,
      liquidityNeed: liquidity as String?,
      maxDrawdownTolerancePct: drawdown as int?,
      availableCapital: (availableCapital as num?)?.toDouble(),
    );
  }

  Map<String, dynamic> toJson() {
    final risk = riskTolerance.trim();
    final currency = baseCurrency.trim().toUpperCase();
    final targetObjective = objective.trim();
    final experience = experienceLevel?.trim();
    final liquidity = liquidityNeed?.trim();
    final drawdown = maxDrawdownTolerancePct;
    final capital = availableCapital;
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
    if (experience != null &&
        experience.isNotEmpty &&
        !experienceLevels.contains(experience)) {
      throw ArgumentError.value(experienceLevel, 'experienceLevel');
    }
    if (liquidity != null &&
        liquidity.isNotEmpty &&
        !liquidityNeeds.contains(liquidity)) {
      throw ArgumentError.value(liquidityNeed, 'liquidityNeed');
    }
    if (drawdown != null && (drawdown < 5 || drawdown > 60)) {
      throw ArgumentError.value(drawdown, 'maxDrawdownTolerancePct');
    }
    if (capital != null &&
        (!capital.isFinite || capital < 0 || capital > maxAvailableCapital)) {
      throw ArgumentError.value(capital, 'availableCapital');
    }
    return {
      'riskTolerance': risk,
      'investmentHorizonYears': investmentHorizonYears,
      'baseCurrency': currency,
      'objective': targetObjective,
      if (experience != null && experience.isNotEmpty)
        'experienceLevel': experience,
      if (liquidity != null && liquidity.isNotEmpty)
        'liquidityNeed': liquidity,
      if (drawdown != null) 'maxDrawdownTolerancePct': drawdown,
      if (capital != null) 'availableCapital': capital,
    };
  }
}
