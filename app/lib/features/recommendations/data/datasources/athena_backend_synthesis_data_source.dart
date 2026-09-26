import 'dart:convert';

import 'package:http/http.dart' as http;

class AthenaSynthesisProvenance {
  final String inputFingerprint;
  final bool hasNews;
  final bool hasInvestors;

  const AthenaSynthesisProvenance({
    required this.inputFingerprint,
    required this.hasNews,
    required this.hasInvestors,
  });
}

class AthenaSynthesisView {
  final String summary;
  final String rationale;
  final List<String> uncertainties;
  final List<String> evidenceIds;
  final bool recommendationInfluence;
  final bool automaticTrading;
  final AthenaSynthesisProvenance provenance;

  const AthenaSynthesisView({
    required this.summary,
    required this.rationale,
    required this.uncertainties,
    required this.evidenceIds,
    required this.recommendationInfluence,
    required this.automaticTrading,
    required this.provenance,
  });

  bool get isSafe => !recommendationInfluence && !automaticTrading;
}

class AthenaBackendSynthesisDataSource {
  final String baseUrl;
  final http.Client client;

  AthenaBackendSynthesisDataSource({
    required this.baseUrl,
    http.Client? client,
  }) : client = client ?? http.Client();

  Future<AthenaSynthesisView> getLatest() async {
    final response = await client.get(Uri.parse(
      '$baseUrl/api/v1/recommendations/professional-research/athena-synthesis/latest',
    ));
    return _decodeResponse(response);
  }

  Future<AthenaSynthesisView> getForResearchCycle(String cycleHash) async {
    final hash = cycleHash.trim().toLowerCase();
    if (!_sha256(hash)) {
      throw ArgumentError.value(cycleHash, 'cycleHash', 'Debe ser SHA-256 hexadecimal.');
    }
    final response = await client.get(Uri.parse(
      '$baseUrl/api/v1/recommendations/professional-research/research-cycle/$hash/athena-synthesis',
    ));
    return _decodeResponse(response);
  }

  AthenaSynthesisView _decodeResponse(http.Response response) {
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(
        'El backend de ATHENA TYCHE respondió con código HTTP ${response.statusCode} al leer la síntesis ATHENA.',
      );
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic> || decoded['data'] is! Map) {
      throw const FormatException('La respuesta ATHENA no respeta el contrato esperado.');
    }
    return _map(Map<String, dynamic>.from(decoded['data'] as Map));
  }

  AthenaSynthesisView _map(Map<String, dynamic> data) {
    if (data['artifactBindingVerified'] is! bool || data['artifactBindingVerified'] != true) {
      throw const FormatException('ATHENA synthesis no acredita artifact binding.');
    }
    if (data['presentationOnly'] is! bool || data['presentationOnly'] != true ||
        data['recommendationInfluence'] is! bool || data['recommendationInfluence'] != false ||
        data['automaticTrading'] is! bool || data['automaticTrading'] != false) {
      throw const FormatException('ATHENA synthesis viola el contrato superior de presentación segura.');
    }
    final rawSynthesis = data['synthesis'];
    final rawProvenance = data['provenance'];
    if (rawSynthesis is! Map || rawProvenance is! Map) {
      throw const FormatException('ATHENA synthesis carece de synthesis/provenance.');
    }
    final synthesis = Map<String, dynamic>.from(rawSynthesis);
    final provenance = Map<String, dynamic>.from(rawProvenance);
    final inputFingerprint = _string(provenance['inputFingerprint'], 'provenance.inputFingerprint').toLowerCase();
    if (!_sha256(inputFingerprint)) {
      throw const FormatException('provenance.inputFingerprint debe ser SHA-256 hexadecimal.');
    }
    if (_string(synthesis['inputFingerprint'], 'synthesis.inputFingerprint').toLowerCase() != inputFingerprint) {
      throw const FormatException('ATHENA synthesis y provenance no comparten inputFingerprint.');
    }
    final recommendationInfluence = _bool(synthesis['recommendationInfluence'], 'recommendationInfluence');
    final automaticTrading = _bool(synthesis['automaticTrading'], 'automaticTrading');
    if (recommendationInfluence || automaticTrading) {
      throw const FormatException('ATHENA synthesis viola el contrato advisory/read-only.');
    }
    final evidenceIds = _strings(synthesis['evidenceIds'], 'evidenceIds');
    if (evidenceIds.toSet().length != evidenceIds.length) {
      throw const FormatException('ATHENA synthesis contiene evidenceIds duplicados.');
    }
    final uncertainties = _strings(synthesis['uncertainties'], 'uncertainties');
    final newsEvidenceIds = _artifactEvidenceIds(provenance['news'], 'news');
    final investorEvidenceIds = _artifactEvidenceIds(provenance['investors'], 'investors');
    final boundEvidenceIds = <String>{...newsEvidenceIds, ...investorEvidenceIds};
    if (boundEvidenceIds.length != newsEvidenceIds.length + investorEvidenceIds.length) {
      throw const FormatException('ATHENA provenance repite evidenceIds entre familias.');
    }
    if (boundEvidenceIds.length != evidenceIds.length ||
        !boundEvidenceIds.containsAll(evidenceIds)) {
      throw const FormatException(
        'ATHENA synthesis contiene evidencia no reconciliada con provenance.',
      );
    }
    return AthenaSynthesisView(
      summary: _string(synthesis['summary'], 'summary'),
      rationale: _string(synthesis['rationale'], 'rationale'),
      uncertainties: List.unmodifiable(uncertainties),
      evidenceIds: List.unmodifiable(evidenceIds),
      recommendationInfluence: false,
      automaticTrading: false,
      provenance: AthenaSynthesisProvenance(
        inputFingerprint: inputFingerprint,
        hasNews: newsEvidenceIds.isNotEmpty,
        hasInvestors: investorEvidenceIds.isNotEmpty,
      ),
    );
  }

  Set<String> _artifactEvidenceIds(dynamic value, String field) {
    if (value == null) return const <String>{};
    if (value is! Map) throw FormatException('provenance.$field debe ser un objeto.');
    final artifact = Map<String, dynamic>.from(value);
    final hash = _string(artifact['artifactHash'], 'provenance.$field.artifactHash').toLowerCase();
    if (!_sha256(hash)) throw FormatException('provenance.$field.artifactHash debe ser SHA-256.');
    if (artifact['userFacingTraceability'] != true ||
        artifact['recommendationInfluence'] != false ||
        artifact['automaticTrading'] != false) {
      throw FormatException('provenance.$field viola el contrato seguro.');
    }
    final bindings = artifact['assessmentBindings'];
    if (bindings is! List || bindings.isEmpty) {
      throw FormatException('provenance.$field carece de assessmentBindings.');
    }
    final seen = <String>{};
    for (final raw in bindings) {
      if (raw is! Map) throw FormatException('provenance.$field contiene un binding inválido.');
      final binding = Map<String, dynamic>.from(raw);
      final evidenceId = _string(binding['evidenceId'], 'provenance.$field.evidenceId');
      final fingerprint = _string(binding['assessmentFingerprint'], 'provenance.$field.assessmentFingerprint').toLowerCase();
      final sourceRef = _string(binding['sourceRef'], 'provenance.$field.sourceRef');
      if (!seen.add(evidenceId) || !_sha256(fingerprint) || !sourceRef.startsWith('https://')) {
        throw FormatException('provenance.$field contiene un binding no verificable.');
      }
    }
    return Set.unmodifiable(seen);
  }

  List<String> _strings(dynamic value, String field) {
    if (value is! List || value.isEmpty) throw FormatException('$field debe ser una lista no vacía.');
    return value.map((item) => _string(item, field)).toList(growable: false);
  }

  String _string(dynamic value, String field) {
    final result = value?.toString().trim() ?? '';
    if (result.isEmpty) throw FormatException('$field es obligatorio.');
    return result;
  }

  bool _bool(dynamic value, String field) {
    if (value is! bool) throw FormatException('$field debe ser booleano.');
    return value;
  }

  bool _sha256(String value) => RegExp(r'^[0-9a-f]{64}$').hasMatch(value);

  void dispose() => client.close();
}