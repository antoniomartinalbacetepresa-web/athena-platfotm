import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/portfolio_allocation_policy.dart';

class AthenaBackendPortfolioAllocationPolicyDataSource {
  final String baseUrl;
  final http.Client client;

  AthenaBackendPortfolioAllocationPolicyDataSource({
    required this.baseUrl,
    http.Client? client,
  }) : client = client ?? http.Client();

  Future<List<PortfolioAllocationPolicy>> listPolicies() async {
    final response = await client.get(
      Uri.parse('$baseUrl/api/v1/portfolio/allocation-policies'),
    );
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(
        'El backend de ATHENA TYCHE respondió con código HTTP ${response.statusCode} al recuperar políticas de allocation.',
      );
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic> || decoded['data'] is! List || decoded['selection'] is! Map) {
      throw const FormatException('La respuesta de políticas de allocation no es válida.');
    }
    final selection = Map<String, dynamic>.from(decoded['selection'] as Map);
    if (selection['explicitSelectionRequired'] != true ||
        selection['policySelectionPerformed'] != false ||
        selection['defaultPolicyExists'] != false ||
        selection['automaticTrading'] != false) {
      throw const FormatException('El backend intentó seleccionar o predeterminar una política de allocation.');
    }

    final policies = <PortfolioAllocationPolicy>[];
    final seenIds = <String>{};
    final seenFingerprints = <String>{};
    for (final raw in decoded['data'] as List) {
      if (raw is! Map) {
        throw const FormatException('Una política persistida no es un objeto válido.');
      }
      final envelope = Map<String, dynamic>.from(raw);
      _validateSafetyEnvelope(envelope);
      final persistence = envelope['persistence'];
      final policyJson = envelope['policy'];
      if (persistence is! Map || policyJson is! Map || persistence['persisted'] != true) {
        throw const FormatException('La política carece de persistencia verificable.');
      }
      final policy = PortfolioAllocationPolicy.fromJson(
        Map<String, dynamic>.from(policyJson),
      );
      final persistenceFingerprint = persistence['policyFingerprint']?.toString().trim().toLowerCase() ?? '';
      if (persistenceFingerprint != policy.policyFingerprint) {
        throw const FormatException('El fingerprint de persistencia no coincide con la política.');
      }
      final persistedAt = DateTime.tryParse(persistence['registeredAt']?.toString() ?? '')?.toUtc();
      if (persistedAt == null || persistedAt != policy.registeredAt) {
        throw const FormatException('registeredAt de persistencia no coincide con la política.');
      }
      if (!seenIds.add(policy.policyId) || !seenFingerprints.add(policy.policyFingerprint)) {
        throw const FormatException('El backend devolvió políticas de allocation duplicadas.');
      }
      policies.add(policy);
    }
    return List.unmodifiable(policies);
  }

  static void _validateSafetyEnvelope(Map<String, dynamic> value) {
    if (value['advisoryStatus'] != 'no_advice' ||
        value['recommendationCandidateReady'] != false ||
        value['productionEligible'] != false ||
        value['allocationEligible'] != false ||
        value['automaticTrading'] != false ||
        value['policySelectionPerformed'] != false ||
        value['defaultPolicyExists'] != false) {
      throw const FormatException('La política violó el contrato no_advice/fail-closed.');
    }
  }

  void dispose() {
    client.close();
  }
}
