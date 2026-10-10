import 'recommendation_shadow_candidate_snapshot.dart';

/// Contexto no autoritativo para preguntar al backend si existe una acción
/// ATHENA sellada que pueda participar en allocation.
///
/// Este objeto NO promueve un candidato shadow, NO selecciona política y NO
/// concede permiso de allocation. Sólo transporta identidad, horizonte y corte
/// PIT ya presentes en evidencia shadow verificable. La autoridad continúa
/// residiendo exclusivamente en backend.
class RecommendationAllocationRequestContext {
  final int instrumentId;
  final int horizonDays;
  final DateTime candidateAsOf;
  final DateTime requestAsOf;
  final String shadowCandidateFingerprint;

  const RecommendationAllocationRequestContext._({
    required this.instrumentId,
    required this.horizonDays,
    required this.candidateAsOf,
    required this.requestAsOf,
    required this.shadowCandidateFingerprint,
  });

  factory RecommendationAllocationRequestContext.fromShadowSnapshot({
    required RecommendationShadowCandidateSnapshot snapshot,
    required int horizonDays,
    required DateTime requestAsOf,
  }) {
    if (!snapshot.isShadowSafe) {
      throw StateError(
        'El contexto de allocation sólo puede partir de evidencia shadow no_advice.',
      );
    }
    final candidate = snapshot.candidate;
    if (candidate == null) {
      throw StateError('No existe candidato shadow verificable.');
    }
    if (!candidate.isShadowSafe) {
      throw StateError('El candidato shadow no cumple el contrato fail-closed.');
    }
    final instrumentId = candidate.instrumentId;
    if (instrumentId == null || instrumentId <= 0) {
      throw StateError(
        'El candidato shadow no tiene identidad canónica de instrumento.',
      );
    }
    if (horizonDays <= 0) {
      throw ArgumentError.value(horizonDays, 'horizonDays');
    }
    final horizon = candidate.horizons[horizonDays];
    if (horizon == null || horizon.horizonDays != horizonDays) {
      throw StateError(
        'El horizonte solicitado no pertenece al candidato shadow.',
      );
    }
    final fingerprint = candidate.candidateFingerprint.trim().toLowerCase();
    if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(fingerprint)) {
      throw StateError(
        'El candidato shadow no expone un fingerprint SHA-256 verificable.',
      );
    }

    final candidateAsOf = candidate.asOf.toUtc();
    final cutoff = requestAsOf.toUtc();
    if (candidateAsOf.isAfter(cutoff)) {
      throw StateError(
        'El candidato shadow es posterior al corte PIT solicitado.',
      );
    }
    final snapshotCandidateAsOf = snapshot.candidateAsOf?.toUtc();
    if (snapshotCandidateAsOf != null && snapshotCandidateAsOf != candidateAsOf) {
      throw StateError(
        'El snapshot y el candidato shadow no comparten el mismo corte PIT.',
      );
    }
    if (snapshot.asOf.toUtc().isBefore(candidateAsOf)) {
      throw StateError(
        'El snapshot fue observado antes que el candidato que contiene.',
      );
    }

    return RecommendationAllocationRequestContext._(
      instrumentId: instrumentId,
      horizonDays: horizonDays,
      candidateAsOf: candidateAsOf,
      requestAsOf: cutoff,
      shadowCandidateFingerprint: fingerprint,
    );
  }
}
