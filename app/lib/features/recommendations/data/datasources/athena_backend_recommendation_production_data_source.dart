import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../models/recommendation_production_state.dart';
import '../../services/recommendation_production_state_provider.dart';

class AthenaBackendRecommendationProductionDataSource
    implements RecommendationProductionStateProvider {
  final String baseUrl;
  final http.Client client;

  AthenaBackendRecommendationProductionDataSource({
    required this.baseUrl,
    http.Client? client,
  }) : client = client ?? http.Client();

  @override
  Future<RecommendationProductionState> getLatest({
    DateTime? asOf,
    String? symbol,
    int? instrumentId,
  }) async {
    final query = <String, String>{};
    if (asOf != null) query['as_of'] = asOf.toUtc().toIso8601String();
    if (symbol != null && symbol.trim().isNotEmpty) {
      query['symbol'] = symbol.trim().toUpperCase();
    }
    if (instrumentId != null) {
      if (instrumentId <= 0) {
        throw ArgumentError.value(instrumentId, 'instrumentId');
      }
      query['instrumentId'] = instrumentId.toString();
    }
    final uri = Uri.parse(
      '$baseUrl/api/v1/recommendations/production/latest',
    ).replace(queryParameters: query.isEmpty ? null : query);
    final response = await client.get(uri);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(
        'El backend de ATHENA TYCHE respondió con código HTTP '
        '${response.statusCode} al verificar el estado productivo.',
      );
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic> || decoded['data'] is! Map) {
      throw const FormatException(
        'La respuesta productiva no respeta el contrato de ATHENA.',
      );
    }
    return _mapState(Map<String, dynamic>.from(decoded['data'] as Map));
  }

  RecommendationProductionState _mapState(Map<String, dynamic> json) {
    final cutoff = _utc(json['asOf'], 'asOf');
    final readOnly = _bool(json['readOnly'], 'readOnly');
    final automaticTrading = _bool(json['automaticTrading'], 'automaticTrading');
    final recommendationAvailable = _bool(
      json['productionRecommendationAvailable'],
      'productionRecommendationAvailable',
    );
    final allocationAvailable = _bool(
      json['productionAllocationAvailable'],
      'productionAllocationAvailable',
    );
    if (!readOnly || automaticTrading || (allocationAvailable && !recommendationAvailable)) {
      throw const FormatException('La lectura productiva viola el contrato seguro de ATHENA.');
    }

    RecommendationProductionRecommendation? recommendation;
    final rawRecommendation = json['recommendation'];
    if (recommendationAvailable) {
      if (rawRecommendation is! Map) {
        throw const FormatException('Falta la recomendación productiva autorizada.');
      }
      recommendation = _mapRecommendation(
        Map<String, dynamic>.from(rawRecommendation),
        cutoff,
      );
    } else if (rawRecommendation != null) {
      throw const FormatException('Existe recomendación sin disponibilidad productiva.');
    }

    RecommendationProductionAllocation? allocation;
    final rawAllocation = json['allocation'];
    if (allocationAvailable) {
      if (rawAllocation is! Map || recommendation == null) {
        throw const FormatException('Falta el allocation productivo autorizado.');
      }
      allocation = _mapAllocation(
        Map<String, dynamic>.from(rawAllocation),
        cutoff,
        recommendation,
      );
    } else if (rawAllocation != null) {
      throw const FormatException('Existe allocation sin disponibilidad productiva.');
    }

    final state = RecommendationProductionState(
      asOf: cutoff,
      recommendation: recommendation,
      allocation: allocation,
      productionRecommendationAvailable: recommendationAvailable,
      productionAllocationAvailable: allocationAvailable,
      automaticTrading: false,
      readOnly: true,
    );
    if (!state.isSafe) {
      throw const FormatException('Estado productivo inconsistente.');
    }
    return state;
  }

  RecommendationProductionRecommendation _mapRecommendation(
    Map<String, dynamic> json,
    DateTime cutoff,
  ) {
    if (_string(json['status'], 'recommendation.status') !=
            'production_recommendation_authorized' ||
        _string(json['advisoryStatus'], 'recommendation.advisoryStatus') !=
            'production_recommendation' ||
        !_bool(json['recommendationCandidateReady'], 'recommendationCandidateReady') ||
        !_bool(json['productionEligible'], 'recommendation.productionEligible') ||
        _bool(json['allocationEligible'], 'recommendation.allocationEligible') ||
        _bool(json['automaticTrading'], 'recommendation.automaticTrading')) {
      throw const FormatException('Contrato de recomendación productiva inválido.');
    }
    final artifactAsOf = _utc(json['asOf'], 'recommendation.asOf');
    final authorizedAt = _utc(json['authorizedAt'], 'recommendation.authorizedAt');
    if (artifactAsOf.isAfter(cutoff) || authorizedAt.isAfter(cutoff)) {
      throw const FormatException('La recomendación productiva viola el cutoff PIT.');
    }
    return RecommendationProductionRecommendation(
      instrumentId: _instrumentId(json['instrumentId'], 'recommendation.instrumentId'),
      symbol: _string(json['symbol'], 'recommendation.symbol').toUpperCase(),
      action: _action(json['action']),
      policyState: _string(json['policyState'], 'recommendation.policyState'),
      asOf: artifactAsOf,
      authorizedAt: authorizedAt,
      authorizationFingerprint: _sha(json['authorizationFingerprint'], 'recommendation.authorizationFingerprint'),
      economicContractFingerprint: _sha(
        json['economicContractFingerprint'],
        'recommendation.economicContractFingerprint',
      ),
    );
  }

  RecommendationProductionAllocation _mapAllocation(
    Map<String, dynamic> json,
    DateTime cutoff,
    RecommendationProductionRecommendation recommendation,
  ) {
    if (_string(json['status'], 'allocation.status') !=
            'production_allocation_authorized' ||
        _string(json['advisoryStatus'], 'allocation.advisoryStatus') !=
            'production_allocation' ||
        !_bool(json['productionEligible'], 'allocation.productionEligible') ||
        !_bool(json['allocationEligible'], 'allocation.allocationEligible') ||
        _bool(json['executionEligible'], 'allocation.executionEligible') ||
        _bool(json['orderRoutingEligible'], 'allocation.orderRoutingEligible') ||
        _bool(json['automaticTrading'], 'allocation.automaticTrading')) {
      throw const FormatException('Contrato de allocation productivo inválido.');
    }
    final instrumentId = _instrumentId(json['instrumentId'], 'allocation.instrumentId');
    final symbol = _string(json['symbol'], 'allocation.symbol').toUpperCase();
    final action = _action(json['action']);
    final artifactAsOf = _utc(json['asOf'], 'allocation.asOf');
    final authorizedAt = _utc(json['authorizedAt'], 'allocation.authorizedAt');
    final recommendationFingerprint = _sha(
      json['recommendationAuthorizationFingerprint'],
      'allocation.recommendationAuthorizationFingerprint',
    );
    final economicFingerprint = _sha(
      json['economicContractFingerprint'],
      'allocation.economicContractFingerprint',
    );
    if (artifactAsOf.isAfter(cutoff) || authorizedAt.isAfter(cutoff)) {
      throw const FormatException('El allocation productivo viola el cutoff PIT.');
    }
    if (instrumentId != recommendation.instrumentId ||
        symbol != recommendation.symbol ||
        action != recommendation.action ||
        recommendationFingerprint != recommendation.authorizationFingerprint ||
        economicFingerprint != recommendation.economicContractFingerprint) {
      throw const FormatException(
        'El allocation no corresponde a la recomendación productiva autorizada.',
      );
    }
    return RecommendationProductionAllocation(
      instrumentId: instrumentId,
      symbol: symbol,
      action: action,
      asOf: artifactAsOf,
      authorizedAt: authorizedAt,
      authorizationFingerprint: _sha(
        json['authorizationFingerprint'],
        'allocation.authorizationFingerprint',
      ),
      recommendationAuthorizationFingerprint: recommendationFingerprint,
      economicContractFingerprint: economicFingerprint,
      baseCurrency: _currency(json['baseCurrency'], 'allocation.baseCurrency'),
      referenceCapital: _positiveFinite(json['referenceCapital'], 'allocation.referenceCapital'),
      targetAmountInBaseCurrency: _nonNegativeFinite(
        json['targetAmountInBaseCurrency'],
        'allocation.targetAmountInBaseCurrency',
      ),
      deltaAmountInBaseCurrency: _finite(
        json['deltaAmountInBaseCurrency'],
        'allocation.deltaAmountInBaseCurrency',
      ),
    );
  }

  DateTime _utc(dynamic value, String field) {
    final parsed = DateTime.tryParse(value?.toString().trim() ?? '');
    if (parsed == null || !parsed.isUtc) {
      throw FormatException('$field debe ser una fecha UTC válida.');
    }
    return parsed;
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

  int _instrumentId(dynamic value, String field) {
    if (value is bool) throw FormatException('$field debe ser entero positivo.');
    final int? parsed;
    if (value is int) {
      parsed = value;
    } else if (value is String && RegExp(r'^[0-9]+$').hasMatch(value.trim())) {
      parsed = int.tryParse(value.trim());
    } else {
      parsed = null;
    }
    if (parsed == null || parsed <= 0) {
      throw FormatException('$field debe ser entero positivo.');
    }
    return parsed;
  }

  String _action(dynamic value) {
    final result = _string(value, 'action').toLowerCase();
    if (!const {'buy', 'hold', 'reduce', 'sell'}.contains(result)) {
      throw const FormatException('Acción productiva no soportada.');
    }
    return result;
  }

  String _currency(dynamic value, String field) {
    final result = _string(value, field).toUpperCase();
    if (!RegExp(r'^[A-Z]{3}$').hasMatch(result)) {
      throw FormatException('$field debe ser moneda ISO de tres letras.');
    }
    return result;
  }

  String _sha(dynamic value, String field) {
    final result = value?.toString().trim().toLowerCase() ?? '';
    if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(result)) {
      throw FormatException('$field debe ser SHA-256 válido.');
    }
    return result;
  }

  double _finite(dynamic value, String field) {
    if (value is bool) throw FormatException('$field debe ser finito.');
    final parsed = value is num ? value.toDouble() : double.tryParse(value?.toString() ?? '');
    if (parsed == null || !parsed.isFinite) {
      throw FormatException('$field debe ser finito.');
    }
    return parsed;
  }

  double _positiveFinite(dynamic value, String field) {
    final parsed = _finite(value, field);
    if (parsed <= 0) throw FormatException('$field debe ser positivo.');
    return parsed;
  }

  double _nonNegativeFinite(dynamic value, String field) {
    final parsed = _finite(value, field);
    if (parsed < 0) throw FormatException('$field no puede ser negativo.');
    return parsed;
  }

  void dispose() => client.close();
}
