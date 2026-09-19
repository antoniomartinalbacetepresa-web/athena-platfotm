import 'dart:convert';

import 'package:http/http.dart' as http;

class ProfessionalModuleState {
  final String status;
  final bool productionEligible;
  final String reason;

  const ProfessionalModuleState({
    required this.status,
    required this.productionEligible,
    required this.reason,
  });
}

class ProfessionalDossier {
  static const moduleNames = <String>{
    'expectationsGap',
    'reverseValuation',
    'scenarioAsymmetry',
    'catalysts',
    'thesisInvalidation',
    'factorRisk',
    'performanceAttribution',
    'investmentJournal',
    'devilsAdvocate',
    'athenaRadar',
  };

  final DateTime asOf;
  final String advisoryStatus;
  final bool productionEligible;
  final bool allocationEligible;
  final bool executionEligible;
  final bool orderRoutingEligible;
  final bool automaticTrading;
  final bool readOnly;
  final Map<String, ProfessionalModuleState> modules;

  const ProfessionalDossier({
    required this.asOf,
    required this.advisoryStatus,
    required this.productionEligible,
    required this.allocationEligible,
    required this.executionEligible,
    required this.orderRoutingEligible,
    required this.automaticTrading,
    required this.readOnly,
    required this.modules,
  });

  bool get isSafe =>
      readOnly &&
      !automaticTrading &&
      !executionEligible &&
      !orderRoutingEligible &&
      modules.length == moduleNames.length &&
      modules.entries.every(
        (entry) =>
            moduleNames.contains(entry.key) &&
            !entry.value.productionEligible,
      );
}

class AthenaBackendProfessionalDossierDataSource {
  final String baseUrl;
  final http.Client client;

  AthenaBackendProfessionalDossierDataSource({
    required this.baseUrl,
    http.Client? client,
  }) : client = client ?? http.Client();

  Future<ProfessionalDossier> getLatest({
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
      '$baseUrl/api/v1/recommendations/production/professional-dossier',
    ).replace(queryParameters: query.isEmpty ? null : query);
    final response = await client.get(uri);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(
        'El backend de ATHENA TYCHE respondió con código HTTP '
        '${response.statusCode} al leer el dossier profesional.',
      );
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic> || decoded['data'] is! Map) {
      throw const FormatException(
        'La respuesta del dossier profesional no respeta el contrato de ATHENA.',
      );
    }
    return _mapDossier(Map<String, dynamic>.from(decoded['data'] as Map));
  }

  ProfessionalDossier _mapDossier(Map<String, dynamic> json) {
    final cutoff = _utc(json['asOf'], 'asOf');
    final advisoryStatus = _string(json['advisoryStatus'], 'advisoryStatus');
    final productionEligible =
        _bool(json['productionEligible'], 'productionEligible');
    final allocationEligible =
        _bool(json['allocationEligible'], 'allocationEligible');
    final executionEligible =
        _bool(json['executionEligible'], 'executionEligible');
    final orderRoutingEligible =
        _bool(json['orderRoutingEligible'], 'orderRoutingEligible');
    final automaticTrading =
        _bool(json['automaticTrading'], 'automaticTrading');
    final readOnly = _bool(json['readOnly'], 'readOnly');

    if (!readOnly || automaticTrading || executionEligible || orderRoutingEligible) {
      throw const FormatException(
        'El dossier profesional viola el contrato seguro de ATHENA.',
      );
    }
    if (advisoryStatus == 'no_advice' &&
        (productionEligible || allocationEligible)) {
      throw const FormatException(
        'Un dossier no_advice no puede declararse elegible para producción o allocation.',
      );
    }

    final rawModules = json['professionalModules'];
    if (rawModules is! Map ||
        rawModules.length != ProfessionalDossier.moduleNames.length) {
      throw const FormatException('Módulos profesionales incompletos.');
    }
    final modules = <String, ProfessionalModuleState>{};
    for (final name in ProfessionalDossier.moduleNames) {
      final raw = rawModules[name];
      if (raw is! Map) {
        throw FormatException('Falta el módulo profesional $name.');
      }
      final module = Map<String, dynamic>.from(raw);
      final production = _bool(
        module['productionEligible'],
        '$name.productionEligible',
      );
      if (production) {
        throw FormatException(
          'El módulo $name no puede marcarse productivo sin evidencia sellada.',
        );
      }
      modules[name] = ProfessionalModuleState(
        status: _string(module['status'], '$name.status'),
        productionEligible: false,
        reason: _string(module['reason'], '$name.reason'),
      );
    }

    final dossier = ProfessionalDossier(
      asOf: cutoff,
      advisoryStatus: advisoryStatus,
      productionEligible: productionEligible,
      allocationEligible: allocationEligible,
      executionEligible: false,
      orderRoutingEligible: false,
      automaticTrading: false,
      readOnly: true,
      modules: Map.unmodifiable(modules),
    );
    if (!dossier.isSafe) {
      throw const FormatException('Dossier profesional inconsistente.');
    }
    return dossier;
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

  void dispose() => client.close();
}
