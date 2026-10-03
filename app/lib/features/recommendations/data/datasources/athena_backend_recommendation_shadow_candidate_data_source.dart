import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../models/recommendation_shadow_candidate_snapshot.dart';
import '../../services/recommendation_shadow_candidate_provider.dart';

class AthenaBackendRecommendationShadowCandidateDataSource
    implements RecommendationShadowCandidateProvider {
  final String baseUrl;
  final http.Client client;

  AthenaBackendRecommendationShadowCandidateDataSource({
    required this.baseUrl,
    http.Client? client,
  }) : client = client ?? http.Client();

  @override
  Future<RecommendationShadowCandidateSnapshot> getLatest({DateTime? asOf}) async {
    final query = <String, String>{};
    if (asOf != null) {
      query['as_of'] = asOf.toUtc().toIso8601String();
    }
    final baseUri = Uri.parse(
      '$baseUrl/api/v1/recommendations/shadow/latest-candidate',
    );
    final uri = baseUri.replace(queryParameters: query.isEmpty ? null : query);
    final response = await client.get(uri);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(
        'El backend de ATHENA TYCHE respondió con código HTTP '
        '${response.statusCode} al verificar el candidato shadow.',
      );
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic> || decoded['data'] is! Map) {
      throw const FormatException(
        'La respuesta del candidato shadow no respeta el contrato de ATHENA.',
      );
    }
    return _mapSnapshot(Map<String, dynamic>.from(decoded['data'] as Map));
  }

  RecommendationShadowCandidateSnapshot _mapSnapshot(Map<String, dynamic> json) {
    final status = _requiredString(json['status'], 'status');
    if (status != 'no_shadow_candidate_known_at_cutoff' &&
        status != 'shadow_candidate_available_non_advisory') {
      throw const FormatException('Estado de candidato shadow no soportado.');
    }
    final snapshotAsOf = _requiredUtc(json['asOf'], 'asOf');
    final advisoryStatus = _requiredString(json['advisoryStatus'], 'advisoryStatus');
    final recommendationReady = _strictBool(
      json['recommendationCandidateReady'],
      'recommendationCandidateReady',
    );
    final productionEligible = _strictBool(
      json['productionEligible'],
      'productionEligible',
    );
    final automaticTrading = _strictBool(
      json['automaticTrading'],
      'automaticTrading',
    );
    if (advisoryStatus != 'no_advice' ||
        recommendationReady ||
        productionEligible ||
        automaticTrading) {
      throw const FormatException(
        'El candidato shadow viola el contrato no_advice de ATHENA.',
      );
    }

    if (status == 'no_shadow_candidate_known_at_cutoff') {
      if (json['candidate'] != null ||
          json['candidateAsOf'] != null ||
          json['persistedAt'] != null ||
          json['recordId'] != null) {
        throw const FormatException(
          'El backend devolvió metadatos de candidato cuando no existe candidato PIT.',
        );
      }
      return RecommendationShadowCandidateSnapshot(
        status: status,
        asOf: snapshotAsOf,
        candidateAsOf: null,
        persistedAt: null,
        recordId: null,
        candidate: null,
        advisoryStatus: advisoryStatus,
        recommendationCandidateReady: recommendationReady,
        productionEligible: productionEligible,
        automaticTrading: automaticTrading,
      );
    }

    final candidateAsOf = _requiredUtc(json['candidateAsOf'], 'candidateAsOf');
    final persistedAt = _requiredUtc(json['persistedAt'], 'persistedAt');
    final recordId = _positiveInt(json['recordId'], 'recordId');
    if (candidateAsOf.isAfter(persistedAt) || persistedAt.isAfter(snapshotAsOf)) {
      throw const FormatException(
        'Las fechas PIT del candidato shadow son inconsistentes.',
      );
    }
    final rawCandidate = json['candidate'];
    if (rawCandidate is! Map) {
      throw const FormatException('Falta el artefacto del candidato shadow.');
    }
    final candidate = _mapCandidate(Map<String, dynamic>.from(rawCandidate));
    if (candidate.asOf != candidateAsOf || candidate.asOf.isAfter(snapshotAsOf)) {
      throw const FormatException(
        'El asOf del artefacto no coincide con la autoridad PIT del backend.',
      );
    }

    return RecommendationShadowCandidateSnapshot(
      status: status,
      asOf: snapshotAsOf,
      candidateAsOf: candidateAsOf,
      persistedAt: persistedAt,
      recordId: recordId,
      candidate: candidate,
      advisoryStatus: advisoryStatus,
      recommendationCandidateReady: recommendationReady,
      productionEligible: productionEligible,
      automaticTrading: automaticTrading,
    );
  }

  RecommendationShadowCandidate _mapCandidate(Map<String, dynamic> json) {
    if (_requiredString(json['artifactVersion'], 'artifactVersion') !=
        'shadow-live-candidate-v1') {
      throw const FormatException('Versión de candidato shadow no soportada.');
    }
    if (_requiredString(json['advisoryStatus'], 'candidate.advisoryStatus') !=
            'no_advice' ||
        _strictBool(
          json['recommendationCandidateReady'],
          'candidate.recommendationCandidateReady',
        ) ||
        _strictBool(json['productionEligible'], 'candidate.productionEligible') ||
        json['action'] != null ||
        json['score'] != null ||
        json['conviction'] != null) {
      throw const FormatException(
        'El artefacto shadow intenta exponer una recomendación no autorizada.',
      );
    }

    final rawHorizons = json['horizons'];
    if (rawHorizons is! Map || rawHorizons.isEmpty) {
      throw const FormatException('El candidato shadow carece de horizontes.');
    }
    final horizons = <int, RecommendationShadowHorizon>{};
    for (final entry in rawHorizons.entries) {
      final horizonDays = int.tryParse(entry.key.toString());
      if (horizonDays == null || horizonDays <= 0 || entry.value is! Map) {
        throw const FormatException('Horizonte shadow inválido.');
      }
      final payload = Map<String, dynamic>.from(entry.value as Map);
      final payloadDays = _positiveInt(payload['horizonDays'], 'horizonDays');
      if (payloadDays != horizonDays || horizons.containsKey(horizonDays)) {
        throw const FormatException('Identidad de horizonte shadow inconsistente.');
      }
      final expected = _nullableFinite(
        payload['expectedExcessReturn'],
        'expectedExcessReturn',
      );
      final modelFingerprint = _nullableSha256(payload['modelFingerprint']);
      final explanation = payload['explanation'] == null
          ? const <String, dynamic>{}
          : _object(payload['explanation'], 'explanation');
      horizons[horizonDays] = RecommendationShadowHorizon(
        horizonDays: horizonDays,
        expectedExcessReturn: expected,
        modelFingerprint: modelFingerprint,
        explanation: explanation,
      );
    }

    return RecommendationShadowCandidate(
      symbol: _requiredString(json['symbol'], 'symbol').toUpperCase(),
      instrumentId: json['instrumentId'] == null
          ? null
          : _positiveInt(json['instrumentId'], 'instrumentId'),
      asOf: _requiredUtc(json['asOf'], 'candidate.asOf'),
      candidateFingerprint: _sha256(
        json['candidateFingerprint'],
        'candidateFingerprint',
      ),
      horizons: horizons,
      riskContext: _optionalObject(json['riskContext']),
      valuationContext: _optionalObject(json['valuationContext']),
      fundamentalContext: _optionalObject(json['fundamentalContext']),
      advisoryStatus: 'no_advice',
      recommendationCandidateReady: false,
      productionEligible: false,
    );
  }

  DateTime _requiredUtc(dynamic value, String field) {
    final parsed = DateTime.tryParse(value?.toString().trim() ?? '');
    if (parsed == null || !parsed.isUtc) {
      throw FormatException('$field debe ser una fecha UTC válida.');
    }
    return parsed;
  }

  String _requiredString(dynamic value, String field) {
    final result = value?.toString().trim() ?? '';
    if (result.isEmpty) {
      throw FormatException('$field es obligatorio.');
    }
    return result;
  }

  bool _strictBool(dynamic value, String field) {
    if (value is! bool) {
      throw FormatException('$field debe ser booleano.');
    }
    return value;
  }

  int _positiveInt(dynamic value, String field) {
    if (value is bool) {
      throw FormatException('$field debe ser entero positivo.');
    }
    int? parsed;
    if (value is int) {
      parsed = value;
    } else if (value is num && value.isFinite && value == value.truncateToDouble()) {
      parsed = value.toInt();
    } else if (value is String) {
      parsed = int.tryParse(value.trim());
    }
    if (parsed == null || parsed <= 0) {
      throw FormatException('$field debe ser entero positivo.');
    }
    return parsed;
  }

  double? _nullableFinite(dynamic value, String field) {
    if (value == null) {
      return null;
    }
    if (value is bool) {
      throw FormatException('$field debe ser finito.');
    }
    final parsed = value is num ? value.toDouble() : double.tryParse(value.toString());
    if (parsed == null || !parsed.isFinite) {
      throw FormatException('$field debe ser finito.');
    }
    return parsed;
  }

  String? _nullableSha256(dynamic value) {
    if (value == null) {
      return null;
    }
    return _sha256(value, 'modelFingerprint');
  }

  String _sha256(dynamic value, String field) {
    final result = value?.toString().trim().toLowerCase() ?? '';
    final valid = result.length == 64 &&
        RegExp(r'^[0-9a-f]{64}$').hasMatch(result);
    if (!valid) {
      throw FormatException('$field debe ser SHA-256 válido.');
    }
    return result;
  }

  Map<String, dynamic> _optionalObject(dynamic value) {
    if (value == null) {
      return const <String, dynamic>{};
    }
    return _object(value, 'context');
  }

  Map<String, dynamic> _object(dynamic value, String field) {
    if (value is! Map) {
      throw FormatException('$field debe ser objeto JSON.');
    }
    return Map<String, dynamic>.from(value);
  }

  void dispose() => client.close();
}
