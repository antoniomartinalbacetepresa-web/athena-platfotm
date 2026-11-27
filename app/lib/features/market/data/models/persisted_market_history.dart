import 'market_data_point.dart';

enum PersistedMarketEvidenceKind { syntheticFixture, unverified }

/// Local replay metadata; no provider rights or historical publication claim.
class PersistedMarketHistory {
  final List<MarketDataPoint> points;
  final DateTime asOf;
  final bool truncated;
  final PersistedMarketEvidenceKind evidenceKind;

  PersistedMarketHistory({
    required List<MarketDataPoint> points,
    required this.asOf,
    required this.truncated,
    this.evidenceKind = PersistedMarketEvidenceKind.unverified,
  }) : points = List.unmodifiable(points);

  /// Source names are only a conservative fixture warning, never real-data proof.
  static PersistedMarketEvidenceKind classifySource(String source) {
    var decoded = source;
    for (var index = 0; index < 8; index++) {
      try {
        final next = Uri.decodeComponent(decoded);
        if (next == decoded) break;
        decoded = next;
      } on FormatException {
        break;
      }
    }
    final markers = decoded.toLowerCase().split(RegExp(r'[^a-z0-9]+'));
    return markers.any(const {'synthetic', 'fixture', 'mock', 'simulated'}.contains)
        ? PersistedMarketEvidenceKind.syntheticFixture
        : PersistedMarketEvidenceKind.unverified;
  }

  static PersistedMarketEvidenceKind parseEvidenceKind(Object? value) {
    if (value == null || value == 'unverified') {
      return PersistedMarketEvidenceKind.unverified;
    }
    if (value == 'synthetic_fixture') {
      return PersistedMarketEvidenceKind.syntheticFixture;
    }
    throw const FormatException('Clasificación de evidencia no admitida.');
  }

  bool get containsSyntheticEvidence =>
      evidenceKind == PersistedMarketEvidenceKind.syntheticFixture ||
      points.any((point) => classifySource(point.sourceProvider ?? '') ==
          PersistedMarketEvidenceKind.syntheticFixture);
}
