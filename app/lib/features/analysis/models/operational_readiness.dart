class OperationalReadiness {
  const OperationalReadiness({
    required this.completionPercent,
    required this.passedGateCount,
    required this.totalGateCount,
    required this.ready,
    required this.blockers,
  });

  final double completionPercent;
  final int passedGateCount;
  final int totalGateCount;
  final bool ready;
  final List<String> blockers;

  factory OperationalReadiness.fromMap(Map<String, dynamic> map) {
    final blockers = map['blockers'];
    return OperationalReadiness(
      completionPercent: (map['completionPercent'] as num?)?.toDouble() ?? 0,
      passedGateCount: (map['passedGateCount'] as num?)?.toInt() ?? 0,
      totalGateCount: (map['totalGateCount'] as num?)?.toInt() ?? 0,
      ready: map['ready'] == true,
      blockers: blockers is List
          ? blockers.map((item) => item.toString()).toList(growable: false)
          : const [],
    );
  }
}

/// Diagnostic snapshot only. This is never production-coverage evidence.
class MarketHistorySnapshot {
  const MarketHistorySnapshot({
    required this.eligibleInstrumentCount,
    required this.currentDeepHistoryInstrumentCount,
    required this.asOf,
  });

  final int eligibleInstrumentCount;
  final int currentDeepHistoryInstrumentCount;
  final DateTime asOf;

  static MarketHistorySnapshot? fromReadiness(Object? raw) {
    if (raw is! Map ||
        raw['status'] != 'diagnostic_only' ||
        raw['pointInTimeCutoffApplied'] != true ||
        raw['productionCoverageClaimed'] != false ||
        raw['sourceContinuityRequired'] != true) {
      return null;
    }
    final active = raw['activeInstrumentCount'];
    final eligible = raw['historyEligibleInstrumentCount'];
    final covered = raw['coveredInstrumentCount'];
    final deep = raw['deepHistoryInstrumentCount'];
    final current = raw['currentDeepHistoryInstrumentCount'];
    final minimumDays = raw['minimumHistoryDays'];
    final maximumGap = raw['maximumSourceGapDays'];
    final asOfText = raw['asOf'];
    if (active is! int ||
        eligible is! int ||
        covered is! int ||
        deep is! int ||
        current is! int ||
        minimumDays is! int ||
        maximumGap is! int ||
        eligible <= 0 ||
        active < eligible ||
        covered < 0 ||
        covered > eligible ||
        deep < 0 ||
        deep > covered ||
        current < 0 ||
        current > deep ||
        minimumDays < 365 ||
        maximumGap < 1 ||
        maximumGap > 7 ||
        asOfText is! String ||
        !RegExp(r'(?:Z|[+-]\d{2}:\d{2})$').hasMatch(asOfText)) {
      return null;
    }
    final asOf = DateTime.tryParse(asOfText);
    if (asOf == null) return null;
    return MarketHistorySnapshot(
      eligibleInstrumentCount: eligible,
      currentDeepHistoryInstrumentCount: current,
      asOf: asOf,
    );
  }
}

class AthenaReadinessReport {
  const AthenaReadinessReport({
    required this.asOf,
    required this.operationalReadiness,
    this.marketHistory,
    this.historyDepthGatePassed = false,
  });

  final DateTime asOf;
  final OperationalReadiness operationalReadiness;
  final MarketHistorySnapshot? marketHistory;
  final bool historyDepthGatePassed;

  factory AthenaReadinessReport.fromMap(Map<String, dynamic> map) {
    final operational = map['operationalReadiness'];
    if (operational is! Map) {
      throw const FormatException('ATHENA readiness perdió operationalReadiness.');
    }
    final asOfText = map['asOf'];
    final asOf = asOfText is String &&
            RegExp(r'(?:Z|[+-]\d{2}:\d{2})$').hasMatch(asOfText)
        ? DateTime.tryParse(asOfText)
        : null;
    if (asOf == null) {
      throw const FormatException('ATHENA readiness perdió asOf válido.');
    }
    final history = MarketHistorySnapshot.fromReadiness(map['marketHistory']);
    final gates = operational['gates'];
    final historyGatePassed = gates is List &&
        gates.any((gate) =>
            gate is Map &&
            gate['id'] == 'market_history_depth' &&
            gate['passed'] == true);
    return AthenaReadinessReport(
      asOf: asOf,
      operationalReadiness: OperationalReadiness.fromMap(
        Map<String, dynamic>.from(operational),
      ),
      marketHistory: history,
      historyDepthGatePassed: history != null &&
          history.asOf.isAtSameMomentAs(asOf) &&
          history.currentDeepHistoryInstrumentCount ==
              history.eligibleInstrumentCount &&
          historyGatePassed,
    );
  }
}
