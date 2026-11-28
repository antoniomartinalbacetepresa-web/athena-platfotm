import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../models/recommendation_learning_status.dart';
import '../../services/recommendation_learning_status_provider.dart';

class AthenaBackendRecommendationLearningDataSource
    implements RecommendationLearningStatusProvider {
  final String baseUrl;
  final http.Client client;

  AthenaBackendRecommendationLearningDataSource({
    required this.baseUrl,
    http.Client? client,
  }) : client = client ?? http.Client();

  @override
  Future<RecommendationLearningStatus> getStatus({
    DateTime? asOf,
    String? modelVersion,
    int? horizonDays,
  }) async {
    final query = <String, String>{};

    if (asOf != null) {
      query['as_of'] = asOf.toUtc().toIso8601String();
    }
    if (modelVersion != null && modelVersion.trim().isNotEmpty) {
      query['modelVersion'] = modelVersion.trim();
    }
    if (horizonDays != null) {
      if (horizonDays <= 0) {
        throw ArgumentError.value(
          horizonDays,
          'horizonDays',
          'Debe ser mayor que 0.',
        );
      }
      query['horizonDays'] = horizonDays.toString();
    }

    final baseUri = Uri.parse(
      '$baseUrl/api/v1/recommendations/learning/status',
    );
    final uri = baseUri.replace(queryParameters: query.isEmpty ? null : query);
    final response = await client.get(uri);

    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(
        'El backend de ATHENA TYCHE respondió con código HTTP '
        '${response.statusCode} al obtener el estado de aprendizaje.',
      );
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw const FormatException(
        'La respuesta de aprendizaje del backend no es un objeto JSON válido.',
      );
    }

    final data = decoded['data'];
    if (data is! Map) {
      throw const FormatException(
        'La respuesta de aprendizaje del backend no contiene un objeto data válido.',
      );
    }

    return _mapStatus(Map<String, dynamic>.from(data));
  }

  RecommendationLearningStatus _mapStatus(Map<String, dynamic> json) {
    final asOfRaw = json['asOf']?.toString().trim();
    final parsedAsOf = asOfRaw == null ? null : DateTime.tryParse(asOfRaw);
    if (parsedAsOf == null || !parsedAsOf.isUtc) {
      throw const FormatException(
        'El estado de aprendizaje no contiene un asOf UTC válido.',
      );
    }

    final filtersRaw = json['filters'];
    final filters = filtersRaw is Map
        ? Map<String, dynamic>.from(filtersRaw)
        : const <String, dynamic>{};
    final shadowLiveLongitudinal = _mapObject(json['shadowLiveLongitudinal']);
    final advisoryStatus = json['advisoryStatus']?.toString().trim() ?? '';
    final productionEligible = _strictBool(
      json['productionEligible'],
      'productionEligible',
    );
    final automaticModelMutation = _strictBool(
      json['automaticModelMutation'],
      'automaticModelMutation',
    );
    final automaticProductionPromotion = _strictBool(
      json['automaticProductionPromotion'],
      'automaticProductionPromotion',
    );
    final automaticTrading = _strictBool(
      json['automaticTrading'],
      'automaticTrading',
    );

    if (advisoryStatus != 'no_advice' ||
        productionEligible ||
        automaticModelMutation ||
        automaticProductionPromotion ||
        automaticTrading) {
      throw const FormatException(
        'El backend devolvió un estado de aprendizaje incompatible con el contrato shadow seguro.',
      );
    }
    _validateShadowLongitudinal(shadowLiveLongitudinal);

    return RecommendationLearningStatus(
      status: json['status']?.toString().trim() ?? 'unknown',
      asOf: parsedAsOf,
      modelVersion: _nullableString(filters['modelVersion']),
      horizonDays: _nullablePositiveInt(filters['horizonDays']),
      performance: _mapObject(json['performance']),
      calibration: _mapObject(json['calibration']),
      evaluationSchedule: _mapObject(json['evaluationSchedule']),
      drift: json['drift'] == null ? null : _mapObject(json['drift']),
      shadowLiveLongitudinal: shadowLiveLongitudinal,
      advisoryStatus: advisoryStatus,
      productionEligible: productionEligible,
      automaticModelMutation: automaticModelMutation,
      automaticProductionPromotion: automaticProductionPromotion,
      automaticTrading: automaticTrading,
    );
  }

  void _validateShadowLongitudinal(Map<String, dynamic> value) {
    if (value['advisoryStatus']?.toString().trim() != 'no_advice' ||
        _strictBool(value['productionEligible'], 'shadow.productionEligible') ||
        _strictBool(
          value['recommendationCandidateReady'],
          'shadow.recommendationCandidateReady',
        )) {
      throw const FormatException(
        'El estado longitudinal shadow no mantiene el contrato no_advice.',
      );
    }

    for (final field in const [
      'persistedCandidateCount',
      'eligibleCandidateCount',
      'evaluatedCandidateCount',
      'evaluatedObservationCount',
      'skippedFutureCandidateCount',
    ]) {
      _requiredNonNegativeInt(value[field], 'shadow.$field');
    }

    final policy = _mapObject(value['policy']);
    if (_strictBool(policy['automaticModelMutation'], 'shadow.automaticModelMutation') ||
        _strictBool(
          policy['automaticProductionPromotion'],
          'shadow.automaticProductionPromotion',
        ) ||
        _strictBool(policy['automaticTrading'], 'shadow.automaticTrading')) {
      throw const FormatException(
        'El estado longitudinal shadow intenta habilitar automatismos productivos.',
      );
    }
  }

  Map<String, dynamic> _mapObject(dynamic value) {
    if (value is! Map) {
      throw const FormatException(
        'El estado de aprendizaje contiene una sección con formato inválido.',
      );
    }
    return Map<String, dynamic>.from(value);
  }

  String? _nullableString(dynamic value) {
    if (value == null) {
      return null;
    }
    final normalized = value.toString().trim();
    return normalized.isEmpty ? null : normalized;
  }

  int? _nullablePositiveInt(dynamic value) {
    if (value == null) {
      return null;
    }
    final parsed = _requiredNonNegativeInt(value, 'horizonDays');
    if (parsed <= 0) {
      throw const FormatException('horizonDays debe ser positivo.');
    }
    return parsed;
  }

  int _requiredNonNegativeInt(dynamic value, String field) {
    if (value is bool) {
      throw FormatException('$field debe ser un entero no negativo.');
    }
    int? parsed;
    if (value is int) {
      parsed = value;
    } else if (value is num) {
      if (!value.isFinite || value != value.truncateToDouble()) {
        throw FormatException('$field debe ser un entero no negativo.');
      }
      parsed = value.toInt();
    } else if (value is String) {
      parsed = int.tryParse(value.trim());
    }
    if (parsed == null || parsed < 0) {
      throw FormatException('$field debe ser un entero no negativo.');
    }
    return parsed;
  }

  bool _strictBool(dynamic value, String field) {
    if (value is! bool) {
      throw FormatException('$field debe ser booleano.');
    }
    return value;
  }

  void dispose() {
    client.close();
  }
}
