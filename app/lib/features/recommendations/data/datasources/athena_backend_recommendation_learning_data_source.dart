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
    if (parsedAsOf == null) {
      throw const FormatException(
        'El estado de aprendizaje no contiene un asOf válido.',
      );
    }

    final filtersRaw = json['filters'];
    final filters = filtersRaw is Map
        ? Map<String, dynamic>.from(filtersRaw)
        : const <String, dynamic>{};

    return RecommendationLearningStatus(
      status: json['status']?.toString().trim() ?? 'unknown',
      asOf: parsedAsOf,
      modelVersion: _nullableString(filters['modelVersion']),
      horizonDays: _nullableInt(filters['horizonDays']),
      performance: _mapObject(json['performance']),
      calibration: _mapObject(json['calibration']),
      evaluationSchedule: _mapObject(json['evaluationSchedule']),
      drift: json['drift'] == null ? null : _mapObject(json['drift']),
      automaticModelMutation: _bool(json['automaticModelMutation']) ?? false,
    );
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

  int? _nullableInt(dynamic value) {
    if (value == null) {
      return null;
    }
    if (value is int) {
      return value;
    }
    if (value is num) {
      return value.toInt();
    }
    return int.tryParse(value.toString().trim());
  }

  bool? _bool(dynamic value) {
    if (value is bool) {
      return value;
    }
    if (value is num) {
      if (value == 1) {
        return true;
      }
      if (value == 0) {
        return false;
      }
    }
    if (value is String) {
      switch (value.trim().toLowerCase()) {
        case 'true':
        case '1':
          return true;
        case 'false':
        case '0':
          return false;
      }
    }
    return null;
  }

  void dispose() {
    client.close();
  }
}
