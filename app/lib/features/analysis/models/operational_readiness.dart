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
    final percent = map['completionPercent'];
    final passed = map['passedGateCount'];
    final total = map['totalGateCount'];
    final blockers = map['blockers'];
    if (percent is! num ||
        !percent.isFinite ||
        percent < 0 ||
        percent > 100 ||
        passed is! int ||
        total is! int ||
        passed < 0 ||
        total <= 0 ||
        passed > total ||
        blockers is! List ||
        !blockers.every((item) => item is String) ||
        map['ready'] is! bool ||
        (percent - (passed / total) * 100).abs() > 0.11) {
      throw const FormatException('ATHENA readiness contiene contadores incoherentes.');
    }
    final verifiedBlockers = List<String>.unmodifiable(blockers);
    return OperationalReadiness(
      completionPercent: percent.toDouble(),
      passedGateCount: passed,
      totalGateCount: total,
      ready: map['ready'] == true &&
          passed == total &&
          percent == 100 &&
          verifiedBlockers.isEmpty,
      blockers: verifiedBlockers,
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
