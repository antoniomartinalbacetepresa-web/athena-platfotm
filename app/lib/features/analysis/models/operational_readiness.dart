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

class AthenaReadinessReport {
  const AthenaReadinessReport({
    required this.asOf,
    required this.operationalReadiness,
  });

  final DateTime asOf;
  final OperationalReadiness operationalReadiness;

  factory AthenaReadinessReport.fromMap(Map<String, dynamic> map) {
    final operational = map['operationalReadiness'];
    if (operational is! Map) {
      throw const FormatException('ATHENA readiness perdió operationalReadiness.');
    }
    final asOf = DateTime.tryParse(map['asOf']?.toString() ?? '');
    if (asOf == null) {
      throw const FormatException('ATHENA readiness perdió asOf válido.');
    }
    return AthenaReadinessReport(
      asOf: asOf,
      operationalReadiness: OperationalReadiness.fromMap(
        Map<String, dynamic>.from(operational),
      ),
    );
  }
}
