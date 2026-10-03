class UserPersonalization {
  static const String supportedSchema = 'athena.user-personalization.v1';

  const UserPersonalization({
    required this.schema,
    required this.fingerprint,
    required this.presentation,
  });

  final String schema;
  final String fingerprint;
  final UserPersonalizationPresentation presentation;

  factory UserPersonalization.fromJson(Map<String, dynamic> json) {
    final schema = json['schema'];
    if (schema != supportedSchema) {
      throw const FormatException('Esquema de personalización no compatible.');
    }

    final fingerprint = json['fingerprint'];
    if (fingerprint is! String ||
        !RegExp(r'^[0-9a-f]{64}$').hasMatch(fingerprint)) {
      throw const FormatException('Fingerprint de personalización no válido.');
    }

    final presentation = json['presentation'];
    if (presentation is! Map<String, dynamic>) {
      throw const FormatException('Presentación personalizada no válida.');
    }

    final policy = json['policy'];
    if (policy is! Map<String, dynamic> ||
        policy['presentationOnly'] != true ||
        policy['recommendationScoringInfluence'] != false ||
        policy['canonicalWeightingInfluence'] != false ||
        policy['automaticLearningPromotion'] != false ||
        policy['automaticTrading'] != false ||
        policy['sensitiveValuesIncluded'] != false) {
      throw const FormatException(
        'La política de personalización no es segura para presentación.',
      );
    }

    return UserPersonalization(
      schema: schema as String,
      fingerprint: fingerprint,
      presentation: UserPersonalizationPresentation.fromJson(presentation),
    );
  }
}

class UserPersonalizationPresentation {
  const UserPersonalizationPresentation({
    required this.detailLevel,
    required this.explanationStyle,
    required this.riskEmphasis,
    required this.horizonEmphasis,
    required this.liquidityEmphasis,
    required this.objectiveFocus,
  });

  static const _detailLevels = {'guided', 'standard', 'technical'};
  static const _explanationStyles = {
    'plain_language',
    'balanced',
    'analytical',
  };
  static const _riskEmphases = {'high', 'standard', 'low'};
  static const _horizonEmphases = {
    'short_term',
    'medium_term',
    'long_term',
  };
  static const _liquidityEmphases = {'unspecified', 'low', 'medium', 'high'};
  static const _objectiveFocuses = {
    'capital_preservation',
    'income',
    'balanced_growth',
    'long_term_growth',
  };

  final String detailLevel;
  final String explanationStyle;
  final String riskEmphasis;
  final String horizonEmphasis;
  final String liquidityEmphasis;
  final String objectiveFocus;

  factory UserPersonalizationPresentation.fromJson(Map<String, dynamic> json) {
    String readAllowed(String key, Set<String> allowed) {
      final value = json[key];
      if (value is! String || !allowed.contains(value)) {
        throw FormatException('Campo de personalización no válido: $key.');
      }
      return value;
    }

    return UserPersonalizationPresentation(
      detailLevel: readAllowed('detailLevel', _detailLevels),
      explanationStyle: readAllowed('explanationStyle', _explanationStyles),
      riskEmphasis: readAllowed('riskEmphasis', _riskEmphases),
      horizonEmphasis: readAllowed('horizonEmphasis', _horizonEmphases),
      liquidityEmphasis: readAllowed('liquidityEmphasis', _liquidityEmphases),
      objectiveFocus: readAllowed('objectiveFocus', _objectiveFocuses),
    );
  }
}
