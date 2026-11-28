import 'dart:convert';

import 'package:http/http.dart' as http;

class AthenaBackendPortfolioAllocationAuthorityResolution {
  final DateTime asOf;
  final int instrumentId;
  final int horizonDays;
  final bool ready;
  final String? reason;
  final String? actionCandidateFingerprint;
  final List<String> correlationEvidenceFingerprints;

  const AthenaBackendPortfolioAllocationAuthorityResolution({
    required this.asOf,
    required this.instrumentId,
    required this.horizonDays,
    required this.ready,
    required this.reason,
    required this.actionCandidateFingerprint,
    required this.correlationEvidenceFingerprints,
  });
}

class AthenaBackendPortfolioAllocationAuthorityDataSource {
  final String baseUrl;
  final http.Client client;

  AthenaBackendPortfolioAllocationAuthorityDataSource({
    required this.baseUrl,
    http.Client? client,
  }) : client = client ?? http.Client();

  Future<AthenaBackendPortfolioAllocationAuthorityResolution> resolve({
    required int instrumentId,
    required int horizonDays,
    required List<int> heldInstrumentIds,
    required DateTime asOf,
  }) async {
    if (instrumentId <= 0) {
      throw ArgumentError.value(instrumentId, 'instrumentId');
    }
    if (horizonDays <= 0) {
      throw ArgumentError.value(horizonDays, 'horizonDays');
    }
    final held = <int>[];
    final seen = <int>{};
    for (final item in heldInstrumentIds) {
      if (item <= 0) {
        throw ArgumentError.value(item, 'heldInstrumentId');
      }
      if (!seen.add(item)) {
        throw StateError('heldInstrumentIds no puede contener duplicados.');
      }
      held.add(item);
    }
    final cutoff = asOf.toUtc();
    final response = await client.post(
      Uri.parse('$baseUrl/api/v1/portfolio/allocation-authorities/resolve'),
      headers: const {'Content-Type': 'application/json'},
      body: jsonEncode({
        'instrumentId': instrumentId,
        'horizonDays': horizonDays,
        'heldInstrumentIds': held,
        'asOf': cutoff.toIso8601String(),
      }),
    );
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(
        'El backend de ATHENA TYCHE respondió con código HTTP ${response.statusCode} al resolver autoridades de allocation.',
      );
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic> || decoded['data'] is! Map) {
      throw const FormatException('La respuesta de autoridades de allocation no contiene data válido.');
    }
    final data = Map<String, dynamic>.from(decoded['data'] as Map);
    _validateSafetyContract(data);
    if (data['artifactVersion'] != 'athena-allocation-authority-resolution-v1') {
      throw const FormatException('Versión de autoridades de allocation no compatible.');
    }
    if (data['callerSuppliedInternalFingerprintsRequired'] != false ||
        data['policySelectionPerformed'] != false ||
        data['economicContractInvented'] != false) {
      throw const FormatException('La resolución de allocation delegó autoridad interna al cliente.');
    }
    final returnedAsOf = DateTime.tryParse(data['asOf']?.toString() ?? '')?.toUtc();
    if (returnedAsOf == null || returnedAsOf != cutoff) {
      throw const FormatException('La resolución cambió el corte PIT solicitado.');
    }
    if (data['instrumentId'] != instrumentId || data['horizonDays'] != horizonDays) {
      throw const FormatException('La resolución cambió instrumento u horizonte.');
    }
    final ready = data['allocationAuthoritiesReady'];
    if (ready is! bool) {
      throw const FormatException('allocationAuthoritiesReady debe ser booleano.');
    }
    final fingerprints = <String>[];
    final rawCorrelations = data['correlationEvidenceFingerprints'];
    if (ready) {
      if (data['status'] != 'allocation_authorities_resolved_non_advisory') {
        throw const FormatException('Estado de autoridades resueltas inválido.');
      }
      final actionFingerprint = _sha256(
        data['uncertaintyBoundActionCandidateFingerprint'],
        'uncertaintyBoundActionCandidateFingerprint',
      );
      if (rawCorrelations is! List) {
        throw const FormatException('Faltan fingerprints de correlación resueltos.');
      }
      final seenFingerprints = <String>{};
      for (final item in rawCorrelations) {
        final fingerprint = _sha256(item, 'correlationEvidenceFingerprint');
        if (!seenFingerprints.add(fingerprint)) {
          throw const FormatException('El backend devolvió correlaciones duplicadas.');
        }
        fingerprints.add(fingerprint);
      }
      return AthenaBackendPortfolioAllocationAuthorityResolution(
        asOf: returnedAsOf,
        instrumentId: instrumentId,
        horizonDays: horizonDays,
        ready: true,
        reason: null,
        actionCandidateFingerprint: actionFingerprint,
        correlationEvidenceFingerprints: List.unmodifiable(fingerprints),
      );
    }

    if (data['status'] != 'allocation_authorities_not_ready') {
      throw const FormatException('Estado de autoridades no preparadas inválido.');
    }
    if (data.containsKey('uncertaintyBoundActionCandidateFingerprint') ||
        data.containsKey('correlationEvidenceFingerprints')) {
      throw const FormatException('Una resolución no preparada no debe filtrar autoridades parciales.');
    }
    final reason = data['reason']?.toString().trim() ?? '';
    if (reason.isEmpty) {
      throw const FormatException('Falta la razón fail-closed de autoridades no preparadas.');
    }
    return AthenaBackendPortfolioAllocationAuthorityResolution(
      asOf: returnedAsOf,
      instrumentId: instrumentId,
      horizonDays: horizonDays,
      ready: false,
      reason: reason,
      actionCandidateFingerprint: null,
      correlationEvidenceFingerprints: const [],
    );
  }

  static void _validateSafetyContract(Map<String, dynamic> data) {
    if (data['advisoryStatus'] != 'no_advice' ||
        data['recommendationCandidateReady'] != false ||
        data['productionEligible'] != false ||
        data['allocationEligible'] != false ||
        data['automaticTrading'] != false) {
      throw const FormatException('Autoridades de allocation violaron el contrato no_advice/fail-closed.');
    }
  }

  static String _sha256(dynamic value, String field) {
    final normalized = value?.toString().trim().toLowerCase() ?? '';
    if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(normalized)) {
      throw FormatException('$field debe ser SHA-256 hexadecimal.');
    }
    return normalized;
  }

  void dispose() {
    client.close();
  }
}
