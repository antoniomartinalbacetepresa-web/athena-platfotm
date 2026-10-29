import 'dart:convert';

import 'package:http/http.dart' as http;

/// Verified, read-only PIT dividend diagnostics; missing values stay unavailable.
/// Percentages are stored as ratios and must never be interpreted as forecasts.
class ProfessionalDividendDiagnostics {
  final String status;
  final String? frequency;
  final double? trailingYield;
  final double? dividendGrowthRate;
  final double? paymentStabilityScore;
  final double? totalReturn60d;
  final double? earningsPayoutRatio;
  final double? fcfPayoutRatio;
  final double? financialSustainabilityScore;

  const ProfessionalDividendDiagnostics({
    required this.status,
    this.frequency,
    this.trailingYield,
    this.dividendGrowthRate,
    this.paymentStabilityScore,
    this.totalReturn60d,
    this.earningsPayoutRatio,
    this.fcfPayoutRatio,
    this.financialSustainabilityScore,
  });
}

class ProfessionalModuleState {
  final String status;
  final bool productionEligible;
  final String reason;
  final bool recommendationInfluence;
  final bool automaticTrading;
  final Map<String, dynamic>? evidence;
  final ProfessionalDividendDiagnostics? dividendDiagnostics;

  const ProfessionalModuleState({
    required this.status,
    required this.productionEligible,
    required this.reason,
    this.recommendationInfluence = false,
    this.automaticTrading = false,
    this.evidence,
    this.dividendDiagnostics,
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
    'dividendTotalReturn',
  };

  final DateTime asOf;
  /// Canonical identity echoed by the verified backend response.
  final String? symbol;
  final int? instrumentId;
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
    this.symbol,
    this.instrumentId,
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
      advisoryStatus == 'no_advice' &&
      !productionEligible &&
      !allocationEligible &&
      readOnly &&
      !automaticTrading &&
      !executionEligible &&
      !orderRoutingEligible &&
      modules.length == moduleNames.length &&
      modules.entries.every(
        (entry) =>
            moduleNames.contains(entry.key) &&
            !entry.value.productionEligible &&
            !entry.value.recommendationInfluence &&
            !entry.value.automaticTrading,
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
    final dossier = _mapDossier(
      Map<String, dynamic>.from(decoded['data'] as Map),
    );
    final requestedSymbol = symbol?.trim().toUpperCase();
    if (requestedSymbol != null &&
        requestedSymbol.isNotEmpty &&
        dossier.symbol != requestedSymbol) {
      throw const FormatException(
        'El dossier profesional no corresponde al símbolo solicitado.',
      );
    }
    if (instrumentId != null && dossier.instrumentId != instrumentId) {
      throw const FormatException(
        'El dossier profesional no corresponde al instrumento solicitado.',
      );
    }
    return dossier;
  }

  ProfessionalDossier _mapDossier(Map<String, dynamic> json) {
    final cutoff = _utc(json['asOf'], 'asOf');
    final dossierSymbol = _optionalSymbol(json['symbol']);
    final dossierInstrumentId = _optionalInstrumentId(json['instrumentId']);
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
    if (advisoryStatus != 'no_advice' ||
        productionEligible ||
        allocationEligible) {
      throw const FormatException(
        'El dossier profesional debe ser no_advice y no elegible para producción o allocation.',
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
      final recommendationInfluence = module.containsKey('recommendationInfluence')
          ? _bool(
              module['recommendationInfluence'],
              '$name.recommendationInfluence',
            )
          : false;
      final moduleAutomaticTrading = module.containsKey('automaticTrading')
          ? _bool(module['automaticTrading'], '$name.automaticTrading')
          : false;
      if (recommendationInfluence || moduleAutomaticTrading) {
        throw FormatException(
          'El módulo $name no puede elevar autoridad de recomendación o trading.',
        );
      }

      Map<String, dynamic>? evidence;
      if (module['evidence'] != null) {
        if (module['evidence'] is! Map) {
          throw FormatException('$name.evidence debe ser un objeto.');
        }
        evidence = Map<String, dynamic>.unmodifiable(
          Map<String, dynamic>.from(module['evidence'] as Map),
        );
      }
      ProfessionalDividendDiagnostics? dividendDiagnostics;
      if (name == 'dividendTotalReturn' &&
          module['status'] == 'diagnostic_evidence_available') {
        if (!module.containsKey('recommendationInfluence') ||
            !module.containsKey('automaticTrading') ||
            evidence == null) {
          throw const FormatException(
            'La evidencia diagnóstica de dividendos debe declarar límites de autoridad y provenance PIT.',
          );
        }
        final knowledgeCutoff = _utc(
          evidence['knowledgeCutoff'],
          'dividendTotalReturn.evidence.knowledgeCutoff',
        );
        if (!knowledgeCutoff.isAtSameMomentAs(cutoff)) {
          throw const FormatException(
            'La evidencia de dividendos no comparte el corte PIT del dossier.',
          );
        }
        if (evidence['productionEligible'] != false ||
            evidence['automaticTrading'] != false) {
          throw const FormatException(
            'La evidencia de dividendos intentó elevar autoridad de producción.',
          );
        }
        dividendDiagnostics = _mapDividendDiagnostics(
          evidence, cutoff, dossierSymbol,
        );
      }

      modules[name] = ProfessionalModuleState(
        status: _string(module['status'], '$name.status'),
        productionEligible: false,
        reason: _string(module['reason'], '$name.reason'),
        recommendationInfluence: recommendationInfluence,
        automaticTrading: moduleAutomaticTrading,
        evidence: evidence,
        dividendDiagnostics: dividendDiagnostics,
      );
    }

    final dossier = ProfessionalDossier(
      asOf: cutoff,
      symbol: dossierSymbol,
      instrumentId: dossierInstrumentId,
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

  ProfessionalDividendDiagnostics _mapDividendDiagnostics(
    Map<String, dynamic> evidence,
    DateTime cutoff,
    String? dossierSymbol,
  ) {
    final rawSignal = evidence['signal'];
    if (rawSignal is! Map<String, dynamic>) {
      throw const FormatException('La señal diagnóstica de dividendos es obligatoria.');
    }
    final signal = rawSignal;
    if (signal['productionEligible'] != false ||
        _utc(signal['asOf'], 'dividend.signal.asOf') != cutoff ||
        dossierSymbol == null ||
        _optionalSymbol(signal['symbol']) != dossierSymbol) {
      throw const FormatException('La señal de dividendos viola identidad, PIT o autoridad.');
    }
    final status = _string(signal['status'], 'dividend.signal.status');
    if (!const {'diagnostic_ready', 'no_dividend_history', 'market_evidence_not_ready'}
        .contains(status)) {
      throw const FormatException('Estado económico de dividendos desconocido.');
    }
    final rawDividend = signal['dividend'];
    if (rawDividend != null && rawDividend is! Map<String, dynamic>) {
      throw const FormatException('Evidencia económica de dividendos inválida.');
    }
    final dividend = rawDividend as Map<String, dynamic>?;
    if (dividend != null) {
      if (dividend['pitSafe'] != true ||
          _utc(dividend['knowledgeCutoff'], 'dividend.knowledgeCutoff') != cutoff) {
        throw const FormatException('Los dividendos no respetan el corte PIT.');
      }
    }
    if ((status == 'diagnostic_ready' && dividend == null) ||
        (status == 'market_evidence_not_ready' && dividend != null)) {
      throw const FormatException('La señal y su disponibilidad económica se contradicen.');
    }
    final frequency = dividend?['frequency'];
    if (frequency != null &&
        !const {'none', 'insufficient_history', 'monthly', 'quarterly',
          'semiannual', 'annual', 'irregular'}.contains(frequency)) {
      throw const FormatException('Frecuencia de dividendos inválida.');
    }
    final rawSustainability = signal['financialPeriodSustainability'];
    if (rawSustainability != null &&
        rawSustainability is! Map<String, dynamic>) {
      throw const FormatException('Sostenibilidad financiera inválida.');
    }
    final sustainability = rawSustainability as Map<String, dynamic>?;
    if (sustainability != null &&
        (sustainability['pitSafe'] != true ||
         _utc(sustainability['knowledgeCutoff'], 'sustainability.knowledgeCutoff') != cutoff ||
         sustainability['sourceProvider'] is! String ||
         (sustainability['sourceProvider'] as String).trim().isEmpty)) {
      throw const FormatException('Sostenibilidad sin procedencia PIT verificable.');
    }
    return ProfessionalDividendDiagnostics(
      status: status,
      frequency: frequency as String?,
      trailingYield: _optionalFiniteRatio(dividend?['trailingYield'], 'trailingYield', minimum: 0),
      dividendGrowthRate: _optionalFiniteRatio(dividend?['dividendGrowthRate'], 'dividendGrowthRate'),
      paymentStabilityScore: _optionalFiniteRatio(
        dividend?['paymentStabilityScore'], 'paymentStabilityScore', minimum: 0, maximum: 1,
      ),
      totalReturn60d: _optionalFiniteRatio(signal['totalReturn60d'], 'totalReturn60d'),
      earningsPayoutRatio: _optionalFiniteRatio(
        signal['earningsPayoutRatio'], 'earningsPayoutRatio', minimum: 0,
      ),
      fcfPayoutRatio: _optionalFiniteRatio(
        signal['fcfPayoutRatio'], 'fcfPayoutRatio', minimum: 0,
      ),
      financialSustainabilityScore: _optionalFiniteRatio(
        sustainability?['sustainabilityScore'], 'sustainabilityScore', minimum: 0, maximum: 1,
      ),
    );
  }

  double? _optionalFiniteRatio(dynamic value, String field,
      {double? minimum, double? maximum}) {
    if (value == null) return null;
    if (value is! num) throw FormatException('$field debe ser numérico.');
    final numeric = value.toDouble();
    if (!numeric.isFinite ||
        (minimum != null && numeric < minimum) ||
        (maximum != null && numeric > maximum)) {
      throw FormatException('$field no es una medida finita válida.');
    }
    return numeric;
  }

  String? _optionalSymbol(dynamic value) {
    if (value == null) return null;
    if (value is! String || value.trim().isEmpty) {
      throw const FormatException('symbol del dossier no es válido.');
    }
    return value.trim().toUpperCase();
  }

  int? _optionalInstrumentId(dynamic value) {
    if (value == null) return null;
    final parsed = value is int
        ? value
        : value is String ? int.tryParse(value) : null;
    if (parsed == null || parsed <= 0) {
      throw const FormatException('instrumentId del dossier no es válido.');
    }
    return parsed;
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
