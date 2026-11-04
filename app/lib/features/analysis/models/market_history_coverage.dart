/// Persisted PIT coverage is diagnostic evidence, never production authority.
class MarketHistoryCoverage {
  const MarketHistoryCoverage({
    required this.asOf,
    required this.eligible,
    required this.covered,
    required this.deep,
    required this.current,
    required this.observations,
    required this.sources,
  });

  final DateTime asOf;
  final int eligible;
  final int covered;
  final int deep;
  final int current;
  final int observations;
  final List<String> sources;

  static DateTime? _awareDate(Object? value) {
    if (value is! String ||
        !RegExp(r'(?:Z|[+-][0-9]{2}:[0-9]{2})$').hasMatch(value)) {
      return null;
    }
    return DateTime.tryParse(value);
  }

  factory MarketHistoryCoverage.fromMap(
    Map<String, dynamic> map, {
    required DateTime expectedAsOf,
  }) {
    final asOf = _awareDate(map['asOf']);
    final active = map['activeInstrumentCount'];
    final eligible = map['historyEligibleInstrumentCount'];
    final covered = map['coveredInstrumentCount'];
    final deep = map['deepHistoryInstrumentCount'];
    final current = map['currentDeepHistoryInstrumentCount'];
    final observations = map['observationCount'];
    final minDays = map['minimumHistoryDays'];
    final maxGap = map['maximumSourceGapDays'];
    final minimumCoverage = map['minimumDeepHistoryCoverage'];
    final rawSources = map['bySource'];

    if (map['status'] != 'diagnostic_only' ||
        map['pointInTimeCutoffApplied'] != true ||
        map['productionCoverageClaimed'] != false ||
        map['sourceContinuityRequired'] != true ||
        asOf == null ||
        !asOf.isAtSameMomentAs(expectedAsOf) ||
        active is! int ||
        eligible is! int ||
        covered is! int ||
        deep is! int ||
        current is! int ||
        observations is! int ||
        eligible < 0 ||
        active < eligible ||
        covered < 0 ||
        covered > eligible ||
        deep < 0 ||
        deep > covered ||
        current < 0 ||
        current > deep ||
        observations < covered ||
        minDays is! int ||
        minDays < 365 ||
        maxGap is! int ||
        maxGap < 1 ||
        maxGap > 7 ||
        minimumCoverage != 1.0 ||
        rawSources is! Map) {
      throw const FormatException('Cobertura histórica PIT inválida.');
    }

    final ratios = <String, double>{
      'instrumentCoverage': eligible == 0 ? 0 : covered / eligible,
      'deepHistoryCoverage': eligible == 0 ? 0 : deep / eligible,
      'currentDeepHistoryCoverage': eligible == 0 ? 0 : current / eligible,
    };
    for (final entry in ratios.entries) {
      final actual = map[entry.key];
      if (actual is! num ||
          !actual.isFinite ||
          (actual - entry.value).abs() > 1e-9) {
        throw const FormatException('Ratios de cobertura PIT incoherentes.');
      }
    }
    if (map['historyDepthReady'] != (observations > 0 && deep == eligible) ||
        map['currentHistoryDepthReady'] !=
            (observations > 0 && current == eligible)) {
      throw const FormatException('Preparación histórica PIT contradictoria.');
    }

    final first = _awareDate(map['earliestObservedAt']);
    final last = _awareDate(map['latestObservedAt']);
    if ((observations == 0 &&
            (map['earliestObservedAt'] != null ||
                map['latestObservedAt'] != null)) ||
        (observations > 0 &&
            (first == null ||
                last == null ||
                first.isAfter(last) ||
                last.isAfter(asOf)))) {
      throw const FormatException('Fechas de observaciones PIT inválidas.');
    }

    var sourceTotal = 0;
    final sources = <String>[];
    for (final entry in rawSources.entries) {
      final provider = entry.key;
      final data = entry.value;
      if (provider is! String ||
          provider.trim().isEmpty ||
          data is! Map ||
          data['observationCount'] is! int ||
          data['coveredInstrumentCount'] is! int) {
        throw const FormatException('Fuente histórica PIT inválida.');
      }
      final count = data['observationCount'] as int;
      final sourceCovered = data['coveredInstrumentCount'] as int;
      final sourceFirst = _awareDate(data['earliestObservedAt']);
      final sourceLast = _awareDate(data['latestObservedAt']);
      if (count <= 0 ||
          sourceCovered <= 0 ||
          sourceCovered > covered ||
          sourceCovered > count ||
          sourceFirst == null ||
          sourceLast == null ||
          sourceFirst.isAfter(sourceLast) ||
          sourceLast.isAfter(asOf)) {
        throw const FormatException('Observaciones por fuente PIT inválidas.');
      }
      sourceTotal += count;
      sources.add('$provider: $count observaciones');
    }
    if (sourceTotal != observations) {
      throw const FormatException('Recuento de fuentes PIT incoherente.');
    }
    sources.sort();
    return MarketHistoryCoverage(
      asOf: asOf,
      eligible: eligible,
      covered: covered,
      deep: deep,
      current: current,
      observations: observations,
      sources: List<String>.unmodifiable(sources),
    );
  }
}
