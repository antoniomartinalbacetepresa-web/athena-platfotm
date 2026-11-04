import '../models/portfolio_position.dart';

class PortfolioPolicyStateContextService {
  const PortfolioPolicyStateContextService();

  Map<String, dynamic> buildForPosition(PortfolioPosition position) {
    if (!position.hasVerifiedCanonicalIdentity) {
      throw StateError(
        'La posición no tiene identidad canónica suficiente para decisiones ATHENA.',
      );
    }
    if (!position.shares.isFinite || position.shares <= 0) {
      throw StateError(
        'La posición debe tener un número de acciones finito y positivo.',
      );
    }
    final state = position.athenaPolicyState;
    if (state == null) {
      throw StateError(
        'La posición no tiene un estado ATHENA explícito. '
        'No se infiere reduced_long/full_long desde el número de acciones.',
      );
    }
    final instrumentId = position.databaseInstrumentId;
    final canonicalInstrumentId = position.canonicalInstrumentId?.trim();
    if (instrumentId == null ||
        instrumentId <= 0 ||
        canonicalInstrumentId == null ||
        canonicalInstrumentId.isEmpty) {
      throw StateError('La posición carece de identidad de instrumento válida.');
    }

    return {
      'instrumentId': instrumentId,
      'canonicalInstrumentId': canonicalInstrumentId,
      'policyState': state.key,
      'positionPresent': true,
      'shares': position.shares,
      'identityRiskReady': position.identityRiskReady,
      'identityExchangeVerified': position.identityExchangeVerified,
    };
  }

  Map<String, dynamic> buildFlat({
    required int instrumentId,
    required String canonicalInstrumentId,
    required bool identityRiskReady,
    required bool identityExchangeVerified,
  }) {
    final canonical = canonicalInstrumentId.trim();
    if (instrumentId <= 0 || canonical.isEmpty) {
      throw ArgumentError(
        'La identidad canónica del instrumento es obligatoria para un estado flat.',
      );
    }
    if (!identityRiskReady || !identityExchangeVerified) {
      throw StateError(
        'La identidad del instrumento no está verificada para decisiones ATHENA.',
      );
    }
    return {
      'instrumentId': instrumentId,
      'canonicalInstrumentId': canonical,
      'policyState': 'flat',
      'positionPresent': false,
      'shares': 0.0,
      'identityRiskReady': true,
      'identityExchangeVerified': true,
    };
  }
}
