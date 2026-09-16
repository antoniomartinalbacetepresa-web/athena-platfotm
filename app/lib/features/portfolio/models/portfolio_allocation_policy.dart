class PortfolioAllocationPolicy {
  static const artifactVersion = 'athena-allocation-policy-v1';

  final String policyId;
  final String baseCurrency;
  final double maximumInstrumentSleeveWeight;
  final double minimumCashReserveWeight;
  final double maximumAbsolutePairCorrelation;
  final int minimumCorrelationSampleCount;
  final int maximumCorrelationAgeSeconds;
  final DateTime registeredAt;
  final String policyFingerprint;

  const PortfolioAllocationPolicy({
    required this.policyId,
    required this.baseCurrency,
    required this.maximumInstrumentSleeveWeight,
    required this.minimumCashReserveWeight,
    required this.maximumAbsolutePairCorrelation,
    required this.minimumCorrelationSampleCount,
    required this.maximumCorrelationAgeSeconds,
    required this.registeredAt,
    required this.policyFingerprint,
  });

  factory PortfolioAllocationPolicy.fromJson(Map<String, dynamic> json) {
    if (json['artifactVersion'] != artifactVersion) {
      throw const FormatException('Versión de política de allocation no compatible.');
    }
    final policyId = json['policyId']?.toString().trim() ?? '';
    if (policyId.isEmpty) {
      throw const FormatException('policyId no puede estar vacío.');
    }
    final baseCurrency = json['baseCurrency']?.toString().trim().toUpperCase() ?? '';
    if (!RegExp(r'^[A-Z]{3}$').hasMatch(baseCurrency)) {
      throw const FormatException('baseCurrency debe ser moneda ISO de tres letras.');
    }
    final sleeve = _finiteDouble(json['maximumInstrumentSleeveWeight'], 'maximumInstrumentSleeveWeight');
    final reserve = _finiteDouble(json['minimumCashReserveWeight'], 'minimumCashReserveWeight');
    final correlation = _finiteDouble(json['maximumAbsolutePairCorrelation'], 'maximumAbsolutePairCorrelation');
    if (sleeve <= 0 || sleeve > 1 || reserve < 0 || reserve > 1 || correlation < 0 || correlation > 1) {
      throw const FormatException('Los límites de allocation deben estar dentro de rangos verificables.');
    }
    if (sleeve > 1 - reserve) {
      throw const FormatException('El sleeve máximo viola la reserva mínima de efectivo.');
    }
    final minimumSamples = _positiveInt(json['minimumCorrelationSampleCount'], 'minimumCorrelationSampleCount');
    final maximumAge = _positiveInt(json['maximumCorrelationAgeSeconds'], 'maximumCorrelationAgeSeconds');
    final registeredAt = DateTime.tryParse(json['registeredAt']?.toString() ?? '')?.toUtc();
    if (registeredAt == null) {
      throw const FormatException('registeredAt debe ser una fecha UTC verificable.');
    }
    final fingerprint = _sha256(json['policyFingerprint'], 'policyFingerprint');

    final semantics = json['semantics'];
    const requiredSemantics = {
      'referenceCapitalIsUserOwnedAllocationBase': true,
      'singleAssetExposureIsNotPortfolioWeight': true,
      'fullLongMeansFillInstrumentSleeveNotWholePortfolio': true,
      'reducedLongScalesInstrumentSleeveByFrozenEconomicContract': true,
      'sellTargetsZeroInstrumentWeight': true,
      'holdPreservesCurrentVerifiedWeight': true,
    };
    if (semantics is! Map ||
        semantics.length != requiredSemantics.length ||
        requiredSemantics.entries.any((entry) => semantics[entry.key] != entry.value)) {
      throw const FormatException('La semántica de capital/allocation no es verificable.');
    }
    final controls = json['policy'];
    if (controls is! Map ||
        controls['codeDefaultTargetWeight'] != false ||
        controls['codeDefaultCorrelationThreshold'] != false ||
        controls['codeDefaultStalenessThreshold'] != false ||
        controls['automaticTrading'] != false) {
      throw const FormatException('La política de allocation contiene defaults o trading automático no permitidos.');
    }

    return PortfolioAllocationPolicy(
      policyId: policyId,
      baseCurrency: baseCurrency,
      maximumInstrumentSleeveWeight: sleeve,
      minimumCashReserveWeight: reserve,
      maximumAbsolutePairCorrelation: correlation,
      minimumCorrelationSampleCount: minimumSamples,
      maximumCorrelationAgeSeconds: maximumAge,
      registeredAt: registeredAt,
      policyFingerprint: fingerprint,
    );
  }

  static double _finiteDouble(dynamic value, String field) {
    if (value is! num) {
      throw FormatException('$field debe ser numérico.');
    }
    final result = value.toDouble();
    if (!result.isFinite) {
      throw FormatException('$field debe ser finito.');
    }
    return result;
  }

  static int _positiveInt(dynamic value, String field) {
    if (value is! int || value <= 0) {
      throw FormatException('$field debe ser entero positivo.');
    }
    return value;
  }

  static String _sha256(dynamic value, String field) {
    final normalized = value?.toString().trim().toLowerCase() ?? '';
    if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(normalized)) {
      throw FormatException('$field debe ser SHA-256 hexadecimal.');
    }
    return normalized;
  }
}
