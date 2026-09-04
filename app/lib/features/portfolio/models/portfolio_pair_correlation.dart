class PortfolioPairCorrelation {
  final int leftInstrumentId;
  final int rightInstrumentId;
  final String sourceProvider;
  final DateTime knowledgeCutoff;
  final int sampleCount;
  final double correlation;
  final DateTime firstReturnDate;
  final DateTime lastReturnDate;
  final DateTime latestRetrievedAt;
  final String priceField;
  final String alignmentPolicy;
  final String returnPolicy;
  final String recommendationPolicy;
  final bool productionEligible;
  final bool allocationInfluence;
  final bool automaticTrading;

  const PortfolioPairCorrelation({
    required this.leftInstrumentId,
    required this.rightInstrumentId,
    required this.sourceProvider,
    required this.knowledgeCutoff,
    required this.sampleCount,
    required this.correlation,
    required this.firstReturnDate,
    required this.lastReturnDate,
    required this.latestRetrievedAt,
    required this.priceField,
    required this.alignmentPolicy,
    required this.returnPolicy,
    required this.recommendationPolicy,
    required this.productionEligible,
    required this.allocationInfluence,
    required this.automaticTrading,
  });

  factory PortfolioPairCorrelation.fromMap(Map<String, dynamic> map) {
    int positiveInt(String key) {
      final value = map[key];
      if (value is! int || value <= 0) {
        throw FormatException('$key debe ser entero positivo.');
      }
      return value;
    }

    String requiredText(String key) {
      final value = map[key]?.toString().trim() ?? '';
      if (value.isEmpty) throw FormatException('$key es obligatorio.');
      return value;
    }

    bool requiredBool(String key) {
      final value = map[key];
      if (value is! bool) throw FormatException('$key debe ser booleano.');
      return value;
    }

    DateTime timestamp(String key) {
      final parsed = DateTime.tryParse(requiredText(key));
      if (parsed == null || parsed.timeZoneOffset != Duration.zero) {
        throw FormatException('$key debe ser un timestamp UTC verificable.');
      }
      return parsed.toUtc();
    }

    DateTime calendarDate(String key) {
      final text = requiredText(key);
      final match = RegExp(r'^(\d{4})-(\d{2})-(\d{2})$').firstMatch(text);
      if (match == null) throw FormatException('$key debe ser fecha AAAA-MM-DD.');
      final year = int.parse(match.group(1)!);
      final month = int.parse(match.group(2)!);
      final day = int.parse(match.group(3)!);
      final value = DateTime.utc(year, month, day);
      if (value.year != year || value.month != month || value.day != day) {
        throw FormatException('$key contiene una fecha inválida.');
      }
      return value;
    }

    final left = positiveInt('leftInstrumentId');
    final right = positiveInt('rightInstrumentId');
    if (left == right) {
      throw const FormatException('La correlación requiere instrumentos distintos.');
    }

    final rawSampleCount = map['sampleCount'];
    if (rawSampleCount is! int || rawSampleCount < 2) {
      throw const FormatException(
        'sampleCount requiere al menos dos rendimientos alineados.',
      );
    }

    final rawCorrelation = map['correlation'];
    if (rawCorrelation is! num) {
      throw const FormatException('correlation debe ser numérica.');
    }
    final correlation = rawCorrelation.toDouble();
    if (!correlation.isFinite || correlation < -1 || correlation > 1) {
      throw const FormatException('correlation debe ser finita y estar en [-1, 1].');
    }

    final cutoff = timestamp('knowledgeCutoff');
    final latestRetrievedAt = timestamp('latestRetrievedAt');
    if (latestRetrievedAt.isAfter(cutoff)) {
      throw const FormatException(
        'La correlación contiene evidencia recuperada después del knowledgeCutoff.',
      );
    }

    final firstReturnDate = calendarDate('firstReturnDate');
    final lastReturnDate = calendarDate('lastReturnDate');
    if (lastReturnDate.isBefore(firstReturnDate)) {
      throw const FormatException('La ventana temporal de correlación es inválida.');
    }

    final priceField = requiredText('priceField');
    final alignmentPolicy = requiredText('alignmentPolicy');
    final returnPolicy = requiredText('returnPolicy');
    final recommendationPolicy = requiredText('recommendationPolicy');
    final productionEligible = requiredBool('productionEligible');
    final allocationInfluence = requiredBool('allocationInfluence');
    final automaticTrading = requiredBool('automaticTrading');

    if (priceField != 'adjusted_close' ||
        alignmentPolicy != 'utc_calendar_date_intersection' ||
        returnPolicy != 'simple_return_consecutive_observations_per_instrument') {
      throw const FormatException('El contrato descriptivo de correlación no coincide.');
    }
    if (recommendationPolicy != 'no_advice' ||
        productionEligible ||
        allocationInfluence ||
        automaticTrading) {
      throw const FormatException(
        'La correlación no puede habilitar advice, producción, asignación ni trading.',
      );
    }

    return PortfolioPairCorrelation(
      leftInstrumentId: left,
      rightInstrumentId: right,
      sourceProvider: requiredText('sourceProvider'),
      knowledgeCutoff: cutoff,
      sampleCount: rawSampleCount,
      correlation: correlation,
      firstReturnDate: firstReturnDate,
      lastReturnDate: lastReturnDate,
      latestRetrievedAt: latestRetrievedAt,
      priceField: priceField,
      alignmentPolicy: alignmentPolicy,
      returnPolicy: returnPolicy,
      recommendationPolicy: recommendationPolicy,
      productionEligible: productionEligible,
      allocationInfluence: allocationInfluence,
      automaticTrading: automaticTrading,
    );
  }
}
