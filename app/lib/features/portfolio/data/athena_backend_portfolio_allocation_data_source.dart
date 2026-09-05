import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/portfolio_position.dart';

class AthenaBackendPortfolioAllocationCandidate {
  final DateTime asOf;
  final String baseCurrency;
  final int instrumentId;
  final String action;
  final String policyState;
  final double referenceCapital;
  final double investedPositionsValueInBaseCurrency;
  final double currentPositionValueInBaseCurrency;
  final double excessOverReferenceCapital;
  final double shortfallVsReferenceCapital;
  final double targetWeight;
  final double targetAmountInBaseCurrency;
  final double deltaAmountInBaseCurrency;
  final bool increasesExposure;
  final String actionCandidateFingerprint;
  final String valuationFingerprint;
  final String allocationCandidateFingerprint;
  final String verifiedPipelineFingerprint;
  final List<String> correlationEvidenceFingerprints;

  const AthenaBackendPortfolioAllocationCandidate({
    required this.asOf,
    required this.baseCurrency,
    required this.instrumentId,
    required this.action,
    required this.policyState,
    required this.referenceCapital,
    required this.investedPositionsValueInBaseCurrency,
    required this.currentPositionValueInBaseCurrency,
    required this.excessOverReferenceCapital,
    required this.shortfallVsReferenceCapital,
    required this.targetWeight,
    required this.targetAmountInBaseCurrency,
    required this.deltaAmountInBaseCurrency,
    required this.increasesExposure,
    required this.actionCandidateFingerprint,
    required this.valuationFingerprint,
    required this.allocationCandidateFingerprint,
    required this.verifiedPipelineFingerprint,
    required this.correlationEvidenceFingerprints,
  });
}

class AthenaBackendPortfolioAllocationDataSource {
  final String baseUrl;
  final http.Client client;

  AthenaBackendPortfolioAllocationDataSource({
    required this.baseUrl,
    http.Client? client,
  }) : client = client ?? http.Client();

  Future<AthenaBackendPortfolioAllocationCandidate> buildAuthorizedCandidate({
    required String uncertaintyBoundActionCandidateFingerprint,
    required String allocationPolicyId,
    required Map<String, Object?> economicContract,
    required double referenceCapital,
    required String baseCurrency,
    required List<PortfolioPosition> positions,
    required List<String> correlationEvidenceFingerprints,
    required DateTime asOf,
  }) async {
    final actionFingerprint = _requiredSha256(
      uncertaintyBoundActionCandidateFingerprint,
      'uncertaintyBoundActionCandidateFingerprint',
    );
    final policyId = allocationPolicyId.trim();
    if (policyId.isEmpty) {
      throw ArgumentError.value(allocationPolicyId, 'allocationPolicyId');
    }
    if (!referenceCapital.isFinite || referenceCapital <= 0) {
      throw ArgumentError.value(referenceCapital, 'referenceCapital');
    }
    final currency = baseCurrency.trim().toUpperCase();
    if (!RegExp(r'^[A-Z]{3}$').hasMatch(currency)) {
      throw ArgumentError.value(baseCurrency, 'baseCurrency');
    }
    final cutoff = asOf.toUtc();
    final correlationFingerprints = <String>[];
    final seenCorrelations = <String>{};
    for (final raw in correlationEvidenceFingerprints) {
      final fingerprint = _requiredSha256(raw, 'correlationEvidenceFingerprint');
      if (!seenCorrelations.add(fingerprint)) {
        throw StateError('No se admiten fingerprints de correlación duplicados.');
      }
      correlationFingerprints.add(fingerprint);
    }

    final payloadPositions = <Map<String, Object?>>[];
    final seenInstrumentIds = <int>{};
    for (final position in positions) {
      final instrumentId = position.databaseInstrumentId;
      if (!position.hasVerifiedCanonicalIdentity || instrumentId == null || instrumentId <= 0) {
        throw StateError('Allocation requiere identidad canónica verificable.');
      }
      if (!position.hasVerifiedPositionProvenance) {
        throw StateError('Allocation requiere provenance verificable de posición.');
      }
      if (!position.shares.isFinite || position.shares <= 0) {
        throw StateError('La cantidad de posición debe ser positiva y finita.');
      }
      if (!seenInstrumentIds.add(instrumentId)) {
        throw StateError('Allocation no admite instrumentos canónicos duplicados.');
      }
      final marketProvider = position.currentPriceSourceProvider?.trim();
      if (marketProvider == null || marketProvider.isEmpty) {
        throw StateError('Allocation requiere proveedor de mercado verificable.');
      }
      final observedAt = position.positionObservedAt!.toUtc();
      final retrievedAt = position.positionRetrievedAt!.toUtc();
      if (retrievedAt.isAfter(cutoff)) {
        throw StateError('La posición fue conocida después del corte PIT.');
      }
      payloadPositions.add({
        'instrumentId': instrumentId,
        'quantity': position.shares,
        'positionSourceProvider': position.positionSourceProvider!.trim(),
        'positionObservedAt': observedAt.toIso8601String(),
        'positionRetrievedAt': retrievedAt.toIso8601String(),
        'marketSourceProvider': marketProvider,
      });
    }

    final uri = Uri.parse('$baseUrl/api/v1/portfolio/allocation-candidate');
    final response = await client.post(
      uri,
      headers: const {'Content-Type': 'application/json'},
      body: jsonEncode({
        'uncertaintyBoundActionCandidateFingerprint': actionFingerprint,
        'allocationPolicyId': policyId,
        'economicContract': economicContract,
        'referenceCapital': referenceCapital,
        'baseCurrency': currency,
        'positions': payloadPositions,
        'correlationEvidenceFingerprints': correlationFingerprints,
        'asOf': cutoff.toIso8601String(),
      }),
    );
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(
        'El backend de ATHENA TYCHE respondió con código HTTP ${response.statusCode} al construir allocation.',
      );
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic> || decoded['data'] is! Map) {
      throw const FormatException('La respuesta de allocation no contiene data válido.');
    }
    final data = Map<String, dynamic>.from(decoded['data'] as Map);
    _validateSafetyContract(data);

    if (data['artifactVersion'] != 'athena-verified-allocation-pipeline-v3' ||
        data['status'] != 'verified_allocation_pipeline_non_advisory' ||
        data['actionAuthorityBoundToAllocation'] != true ||
        data['portfolioValuationBoundToAllocation'] != true ||
        data['portfolioValuationSealedBeforeAllocation'] != true ||
        data['callerSuppliedActionArtifactsAccepted'] != false ||
        data['callerSuppliedValuationTotalsAccepted'] != false ||
        data['correlationAuthorityBoundToAllocation'] != true ||
        data['callerSuppliedCorrelationArtifactsAccepted'] != false) {
      throw const FormatException('Allocation backend no acredita autoridades selladas.');
    }

    final returnedAsOf = DateTime.tryParse(data['asOf']?.toString() ?? '')?.toUtc();
    if (returnedAsOf == null || returnedAsOf != cutoff) {
      throw const FormatException('Allocation backend cambió el corte PIT solicitado.');
    }
    if (data['baseCurrency']?.toString().toUpperCase() != currency) {
      throw const FormatException('Allocation backend cambió la moneda base.');
    }

    final allocationRaw = data['allocationCandidate'];
    if (allocationRaw is! Map) {
      throw const FormatException('Allocation backend carece de candidato verificable.');
    }
    final allocation = Map<String, dynamic>.from(allocationRaw);
    _validateSafetyContract(allocation);
    if (allocation['status'] != 'allocation_candidate_non_advisory' ||
        allocation['allocationEvidenceStructurallyReady'] != true) {
      throw const FormatException('El candidato de allocation no está estructuralmente verificado.');
    }
    if (allocation['baseCurrency']?.toString().toUpperCase() != currency ||
        DateTime.tryParse(allocation['asOf']?.toString() ?? '')?.toUtc() != cutoff) {
      throw const FormatException('El candidato de allocation no coincide con moneda/asOf solicitados.');
    }

    final returnedReference = _finitePositive(allocation['referenceCapital'], 'referenceCapital');
    if ((returnedReference - referenceCapital).abs() > 1e-9) {
      throw const FormatException('Allocation backend cambió el capital de referencia.');
    }
    final actionFp = _requiredSha256(
      data['uncertaintyBoundActionCandidateFingerprint']?.toString() ?? '',
      'returnedActionFingerprint',
    );
    if (actionFp != actionFingerprint ||
        allocation['uncertaintyBoundActionCandidateFingerprint']?.toString().toLowerCase() != actionFingerprint) {
      throw const FormatException('Allocation backend cambió la autoridad de acción.');
    }

    final authoritiesRaw = data['correlationAuthority'];
    if (authoritiesRaw is! List) {
      throw const FormatException('Allocation backend carece de autoridad de correlación.');
    }
    final returnedCorrelationFingerprints = <String>[];
    for (final item in authoritiesRaw) {
      if (item is! Map) {
        throw const FormatException('Autoridad de correlación inválida.');
      }
      returnedCorrelationFingerprints.add(
        _requiredSha256(item['evidenceFingerprint']?.toString() ?? '', 'correlationAuthority'),
      );
      _requiredSha256(item['recordFingerprint']?.toString() ?? '', 'correlationRecord');
      if (DateTime.tryParse(item['persistedAt']?.toString() ?? '') == null) {
        throw const FormatException('Autoridad de correlación sin persistedAt válido.');
      }
    }
    if (returnedCorrelationFingerprints.length != correlationFingerprints.length ||
        !returnedCorrelationFingerprints.toSet().containsAll(correlationFingerprints)) {
      throw const FormatException('Allocation backend cambió las autoridades de correlación solicitadas.');
    }

    return AthenaBackendPortfolioAllocationCandidate(
      asOf: returnedAsOf,
      baseCurrency: currency,
      instrumentId: _positiveInt(data['instrumentId'], 'instrumentId'),
      action: allocation['action']?.toString() ?? '',
      policyState: allocation['policyState']?.toString() ?? '',
      referenceCapital: returnedReference,
      investedPositionsValueInBaseCurrency: _finiteNonNegative(
        data['investedPositionsValueInBaseCurrency'],
        'investedPositionsValueInBaseCurrency',
      ),
      currentPositionValueInBaseCurrency: _finiteNonNegative(
        data['currentPositionValueInBaseCurrency'],
        'currentPositionValueInBaseCurrency',
      ),
      excessOverReferenceCapital: _finiteNonNegative(
        allocation['excessOverReferenceCapital'],
        'excessOverReferenceCapital',
      ),
      shortfallVsReferenceCapital: _finiteNonNegative(
        allocation['shortfallVsReferenceCapital'],
        'shortfallVsReferenceCapital',
      ),
      targetWeight: _unit(allocation['targetWeight'], 'targetWeight'),
      targetAmountInBaseCurrency: _finiteNonNegative(
        allocation['targetAmountInBaseCurrency'],
        'targetAmountInBaseCurrency',
      ),
      deltaAmountInBaseCurrency: _finite(
        allocation['deltaAmountInBaseCurrency'],
        'deltaAmountInBaseCurrency',
      ),
      increasesExposure: _strictBool(allocation['increasesExposure'], 'increasesExposure'),
      actionCandidateFingerprint: actionFp,
      valuationFingerprint: _requiredSha256(
        data['portfolioValuationEvidenceFingerprint']?.toString() ?? '',
        'portfolioValuationEvidenceFingerprint',
      ),
      allocationCandidateFingerprint: _requiredSha256(
        data['allocationCandidateFingerprint']?.toString() ?? '',
        'allocationCandidateFingerprint',
      ),
      verifiedPipelineFingerprint: _requiredSha256(
        data['verifiedAllocationPipelineFingerprint']?.toString() ?? '',
        'verifiedAllocationPipelineFingerprint',
      ),
      correlationEvidenceFingerprints: List.unmodifiable(returnedCorrelationFingerprints),
    );
  }

  static void _validateSafetyContract(Map<String, dynamic> data) {
    if (data['advisoryStatus'] != 'no_advice' ||
        data['recommendationCandidateReady'] != false ||
        data['productionEligible'] != false ||
        data['allocationEligible'] != false ||
        data['automaticTrading'] != false) {
      throw const FormatException('Allocation violó el contrato no_advice/fail-closed.');
    }
  }

  static String _requiredSha256(String value, String field) {
    final normalized = value.trim().toLowerCase();
    if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(normalized)) {
      throw FormatException('$field debe ser SHA-256 hexadecimal.');
    }
    return normalized;
  }

  static double _finite(dynamic value, String field) {
    if (value is! num || !value.toDouble().isFinite) {
      throw FormatException('$field debe ser finito.');
    }
    return value.toDouble();
  }

  static double _finiteNonNegative(dynamic value, String field) {
    final result = _finite(value, field);
    if (result < 0) throw FormatException('$field no puede ser negativo.');
    return result;
  }

  static double _finitePositive(dynamic value, String field) {
    final result = _finite(value, field);
    if (result <= 0) throw FormatException('$field debe ser positivo.');
    return result;
  }

  static double _unit(dynamic value, String field) {
    final result = _finite(value, field);
    if (result < 0 || result > 1) throw FormatException('$field debe estar entre 0 y 1.');
    return result;
  }

  static int _positiveInt(dynamic value, String field) {
    if (value is! int || value <= 0) throw FormatException('$field debe ser entero positivo.');
    return value;
  }

  static bool _strictBool(dynamic value, String field) {
    if (value is! bool) throw FormatException('$field debe ser booleano.');
    return value;
  }

  void dispose() {
    client.close();
  }
}
