import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../auth/services/auth_session.dart';

/// Read-only owner-scoped research index. Never falls back to public routes.
class PrivateResearchHistoryService {
  PrivateResearchHistoryService({
    String baseUrl = const String.fromEnvironment(
      'ATHENA_BACKEND_URL', defaultValue: 'http://127.0.0.1:8000'),
    http.Client? client,
    AuthSession? session,
  })  : _baseUrl = baseUrl.replaceAll(RegExp(r'/+$'), ''),
        _client = client ?? http.Client(),
        _ownsClient = client == null,
        _session = session ?? AuthSession.instance;

  final String _baseUrl;
  final http.Client _client;
  final bool _ownsClient;
  final AuthSession _session;

  static const Duration requestTimeout = Duration(seconds: 15);
  static const int maxResponseBytes = 256 * 1024;

  Future<PrivateResearchPage> load({required String symbol, int limit = 20}) async {
    final normalized = symbol.trim().toUpperCase();
    if (!RegExp(r'^[A-Z0-9][A-Z0-9.-]{0,19}$').hasMatch(normalized)) {
      throw const FormatException('Símbolo de investigación inválido.');
    }
    if (limit < 1 || limit > 50) {
      throw RangeError.range(limit, 1, 50, 'limit');
    }
    final token = _session.accessToken;
    if (!_session.isAuthenticated || token == null || token.trim().isEmpty) {
      throw StateError('Se requiere autenticación para consultar investigaciones privadas.');
    }
    final version = _session.authorityVersion;
    final uri = Uri.parse('$_baseUrl/api/v1/recommendations/professional-research/research-cycle/private')
        .replace(queryParameters: {'symbol': normalized, 'limit': '$limit'});
    final response = await _client
        .get(uri, headers: {'Authorization': 'Bearer $token'})
        .timeout(requestTimeout);
    if (_session.authorityVersion != version ||
        !_session.isAuthenticated || _session.accessToken != token) {
      throw StateError('La sesión cambió durante la consulta privada.');
    }
    if (response.statusCode == 401 || response.statusCode == 403) {
      throw StateError('Acceso privado no autorizado.');
    }
    if (response.statusCode != 200) {
      throw StateError('No se pudo verificar el historial privado.');
    }
    if (response.bodyBytes.length > maxResponseBytes) {
      throw const FormatException('Respuesta privada demasiado grande.');
    }
    final decoded = jsonDecode(utf8.decode(response.bodyBytes));
    if (decoded is! Map<String, dynamic> || decoded['data'] is! Map<String, dynamic>) {
      throw const FormatException('Respuesta privada inválida.');
    }
    final data = decoded['data'] as Map<String, dynamic>;
    if (data['readOnly'] != true ||
        data['metadataOnly'] != true ||
        data['cycleOwnerBindingVerified'] != true ||
        data['advisoryStatus'] != 'no_advice' ||
        data['productionEligible'] != false ||
        data['automaticTrading'] != false ||
        data['licenseVerified'] != false ||
        data['modelExecutionVerified'] != false) {
      throw const FormatException('La respuesta privada incumple el contrato de seguridad.');
    }
    final raw = data['items'];
    if (raw is! List || data['returnedCount'] != raw.length || raw.length > limit) {
      throw const FormatException('Índice privado incoherente.');
    }
    final items = <PrivateResearchEntry>[];
    for (final value in raw) {
      if (value is! Map<String, dynamic> ||
          value['symbol'] != normalized ||
          value['packageIntegrityVerified'] != true) {
        throw const FormatException('Identidad o integridad de investigación inválida.');
      }
      final hash = value['cycleHash'];
      final asOf = DateTime.tryParse(value['asOf'] is String ? value['asOf'] as String : '');
      if (hash is! String || !RegExp(r'^[a-f0-9]{64}$').hasMatch(hash) ||
          asOf == null || !asOf.isUtc || asOf.isAfter(DateTime.now().toUtc())) {
        throw const FormatException('Hash o corte PIT privado inválido.');
      }
      items.add(PrivateResearchEntry(cycleHash: hash, symbol: normalized, asOf: asOf));
    }
    return PrivateResearchPage(List.unmodifiable(items));
  }

  /// Owner-authorized detail; never retries through a public endpoint.
  Future<PrivateResearchCycleDetail> loadCycle(PrivateResearchEntry entry) => _loadCycle(entry);

  /// Verify a creation response against its frozen human draft in the same read.
  Future<PrivateResearchCycleDetail> loadCycleWithBinding(PrivateResearchEntry entry,
      {required void Function(Map<String, dynamic>) validatePackage}) =>
      _loadCycle(entry, validatePackage: validatePackage);

  Future<PrivateResearchCycleDetail> _loadCycle(PrivateResearchEntry entry,
      {void Function(Map<String, dynamic>)? validatePackage}) async {
    // Reject impossible or malformed research selections before network access.
    // The index is not a substitute for validating an independently supplied entry.
    if (!entry.asOf.isUtc || entry.asOf.isAfter(DateTime.now().toUtc()) ||
        !RegExp(r'^[a-f0-9]{64}$').hasMatch(entry.cycleHash) ||
        !RegExp(r'^[A-Z0-9][A-Z0-9.-]{0,19}$').hasMatch(entry.symbol)) {
      throw const FormatException('Identificador privado inválido.');
    }
    final token = _session.accessToken;
    if (!_session.isAuthenticated || token == null || token.trim().isEmpty) {
      throw StateError('Se requiere autenticación.');
    }
    final version = _session.authorityVersion;
    final uri = Uri.parse(
        '$_baseUrl/api/v1/recommendations/professional-research/research-cycle/private/${entry.cycleHash}');
    final response = await _client
        .get(uri, headers: {'Authorization': 'Bearer $token'})
        .timeout(requestTimeout);
    if (_session.authorityVersion != version ||
        !_session.isAuthenticated || _session.accessToken != token) {
      throw StateError('La sesión cambió durante la consulta privada.');
    }
    if (response.statusCode == 401 || response.statusCode == 403 ||
        response.statusCode == 404) {
      throw StateError('Investigación privada no disponible para esta cuenta.');
    }
    if (response.statusCode != 200) {
      throw StateError('No se pudo verificar la investigación privada.');
    }
    if (response.bodyBytes.length > maxResponseBytes) {
      throw const FormatException('Respuesta privada demasiado grande.');
    }
    final decoded = jsonDecode(utf8.decode(response.bodyBytes));
    if (decoded is! Map<String, dynamic> ||
        decoded['data'] is! Map<String, dynamic>) {
      throw const FormatException('Respuesta privada inválida.');
    }
    final data = decoded['data'] as Map<String, dynamic>;
    if (data['advisoryStatus'] != 'no_advice' ||
        data['productionEligible'] != false ||
        data['automaticTrading'] != false ||
        data['isWeightingReady'] != false ||
        data['package'] is! Map<String, dynamic> ||
        data['persistence'] is! Map<String, dynamic>) {
      throw const FormatException('Contrato privado no verificable.');
    }
    final package = data['package'] as Map<String, dynamic>;
    final persistence = data['persistence'] as Map<String, dynamic>;
    // FastAPI returns a canonical module bundle, not a flattened cycle.
    // Outer metadata must never substitute for the hash-bound cycle identity.
    final cycle = package['cycle'];
    if (cycle is! Map<String, dynamic> ||
        cycle['integrity'] is! Map<String, dynamic>) {
      throw const FormatException('Paquete canónico privado inválido.');
    }
    final integrity = cycle['integrity'] as Map<String, dynamic>;
    final packageAsOf = cycle['asOf'];
    final parsedAsOf = packageAsOf is String ? DateTime.tryParse(packageAsOf) : null;
    if (persistence['cycleHash'] != entry.cycleHash ||
        integrity['algorithm'] != 'sha256' ||
        integrity['cycleHash'] != entry.cycleHash ||
        cycle['symbol'] != entry.symbol ||
        parsedAsOf == null || !parsedAsOf.isUtc ||
        parsedAsOf.isAfter(DateTime.now().toUtc()) ||
        !parsedAsOf.isAtSameMomentAs(entry.asOf)) {
      throw const FormatException('Identidad privada incoherente.');
    }
    validatePackage?.call(package);
    return PrivateResearchCycleDetail(
      symbol: entry.symbol,
      cycleHash: entry.cycleHash,
      asOf: entry.asOf,
      evidence: _evidence(package, entry.asOf),
    );
  }

  List<PrivateResearchEvidence> _evidence(Map<String, dynamic> package, DateTime cutoff) {
    final radar = package['radar'];
    if (radar == null) return const []; // Older minimal detail contracts.
    if (radar is! Map || radar['candidates'] is! List) {
      throw const FormatException('Radar privado inválido.');
    }
    final candidates = radar['candidates'] as List;
    if (candidates.length != 1 || candidates.single is! Map) {
      throw const FormatException('Candidatos privados incompatibles.');
    }
    final rows = (candidates.single as Map)['evidence'];
    if (rows is! List || rows.length > 200) {
      throw const FormatException('Evidencias privadas incompatibles.');
    }
    final result = <PrivateResearchEvidence>[];
    final seen = <String>{};
    for (final row in rows) {
      if (row is! Map) throw const FormatException('Referencia privada inválida.');
      final id = row['evidenceId'];
      final category = row['category'];
      final summary = row['summary'];
      final source = row['source'];
      final ref = row['sourceRef'];
      final available = row['availableAt'] is String ? DateTime.tryParse(row['availableAt'] as String) : null;
      final publication = row['publishedAt'] == null ? null :
          (row['publishedAt'] is String ? DateTime.tryParse(row['publishedAt'] as String) : null);
      if (id is! String || id.isEmpty || !seen.add(id) || category is! String ||
          summary is! String || summary.trim().isEmpty || summary.length > 12000 ||
          source is! String || source.trim().isEmpty || ref is! String || ref.isEmpty ||
          available == null || !available.isUtc || available.isAfter(cutoff) ||
          (row['publishedAt'] != null && (publication == null || !publication.isUtc || publication.isAfter(available)))) {
        throw const FormatException('Identidad o temporalidad de evidencia privada inválida.');
      }
      result.add(PrivateResearchEvidence(id: id, category: category, summary: summary,
        source: source, sourceRef: ref, availableAt: available, publishedAt: publication));
    }
    return List.unmodifiable(result);
  }

  /// Retrieve one canonical synthesis without a public fallback. A missing
  /// synthesis is an explicit absence, not a verified model execution.
  Future<PrivateResearchSynthesis?> loadSynthesis(
      PrivateResearchEntry entry, {required bool athena}) => _loadSynthesis(entry, athena: athena);

  Future<PrivateResearchSynthesis?> loadInvestorsSynthesis(PrivateResearchEntry entry) =>
      _loadSynthesis(entry, athena: false, investors: true);

  Future<PrivateResearchSynthesis?> _loadSynthesis(PrivateResearchEntry entry,
      {required bool athena, bool investors = false}) async {
    // A synthesis must never inherit an impossible future PIT timestamp,
    // even if its canonical cycle hash and owner binding are otherwise valid.
    if (!entry.asOf.isUtc || entry.asOf.isAfter(DateTime.now().toUtc())) {
      throw const FormatException('Corte PIT de síntesis privada inválido.');
    }
    if (!RegExp(r'^[a-f0-9]{64}$').hasMatch(entry.cycleHash) ||
        !RegExp(r'^[A-Z0-9][A-Z0-9.-]{0,19}$').hasMatch(entry.symbol)) {
      throw const FormatException('Identificador privado inválido.');
    }
    final token = _session.accessToken;
    if (!_session.isAuthenticated || token == null || token.trim().isEmpty) {
      throw StateError('Se requiere autenticación.');
    }
    final version = _session.authorityVersion;
    final kind = investors ? 'investors-synthesis' : athena ? 'athena-synthesis' : 'news-synthesis';
    final uri = Uri.parse(
        '$_baseUrl/api/v1/recommendations/professional-research/research-cycle/private/${entry.cycleHash}/$kind');
    final response = await _client.get(
      uri, headers: {'Authorization': 'Bearer $token'},
    ).timeout(requestTimeout);
    if (_session.authorityVersion != version ||
        !_session.isAuthenticated || _session.accessToken != token) {
      throw StateError('La sesión cambió durante la consulta privada.');
    }
    if (response.statusCode == 404) return null;
    if (response.statusCode == 401 || response.statusCode == 403) {
      throw StateError('Acceso privado no autorizado.');
    }
    if (response.statusCode != 200) {
      throw StateError('No se pudo verificar la síntesis privada.');
    }
    if (response.bodyBytes.length > maxResponseBytes) {
      throw const FormatException('Respuesta privada demasiado grande.');
    }
    final decoded = jsonDecode(utf8.decode(response.bodyBytes));
    if (decoded is! Map<String, dynamic> ||
        decoded['data'] is! Map<String, dynamic>) {
      throw const FormatException('Síntesis privada inválida.');
    }
    final data = decoded['data'] as Map<String, dynamic>;
    final synthesis = data['synthesis'];
    final persistence = data['persistence'];
    if (synthesis is! Map<String, dynamic> ||
        persistence is! Map<String, dynamic> ||
        persistence['cycleHash'] != entry.cycleHash ||
        (athena ? data['artifactBindingVerified'] : data['cycleBindingVerified']) != true ||
        synthesis['modelExecutionVerified'] != false ||
        (athena ? data['provenance'] is! Map<String, dynamic> :
            data['automaticTrading'] != false || data['recommendationInfluence'] != false)) {
      throw const FormatException('Vinculación o seguridad de síntesis no verificable.');
    }
    final Object? summary;
    if (investors) {
      final assessments = synthesis['assessments'];
      final provenance = data['provenance'];
      if (synthesis['status'] != 'validated_external_investors_model_output' ||
          synthesis['automaticScoring'] != false || synthesis['independentCorroborationClaimed'] != false ||
          data['cycleHash'] != entry.cycleHash || data['automaticScoring'] != false ||
          synthesis['automaticTrading'] != false || synthesis['recommendationInfluence'] != false ||
          synthesis['productionTruthClaimed'] != false || synthesis['asOf'] is! String ||
          DateTime.tryParse(synthesis['asOf'] as String)?.isUtc != true ||
          DateTime.tryParse(synthesis['asOf'] as String)?.isAtSameMomentAs(entry.asOf) != true ||
          assessments is! List || assessments.isEmpty || assessments.length > 200 ||
          synthesis['assessedCount'] != assessments.length || provenance is! Map ||
          provenance['automaticTrading'] != false || provenance['automaticScoring'] != false ||
          provenance['recommendationInfluence'] != false ||
          provenance['artifactType'] != 'canonical_investors_synthesis' ||
          persistence['synthesisHash'] is! String ||
          !RegExp(r'^[a-f0-9]{64}$').hasMatch(persistence['synthesisHash'] as String) ||
          provenance['artifactHash'] != persistence['synthesisHash'] ||
          provenance['assessmentBindings'] is! List) {
        throw const FormatException('Síntesis Investors no vinculada.');
      }
      final bindings = provenance['assessmentBindings'] as List;
      final ids = <String>{};
      final summaries = <String>[];
      for (final assessment in assessments) {
        if (assessment is! Map || assessment['symbol'] != entry.symbol ||
            assessment['evidenceId'] is! String || !ids.add(assessment['evidenceId'] as String) ||
            assessment['summary'] is! String || (assessment['summary'] as String).trim().isEmpty ||
            assessment['assessmentFingerprint'] is! String ||
            !RegExp(r'^[a-f0-9]{64}$').hasMatch(assessment['assessmentFingerprint'] as String) ||
            assessment['sourceRef'] is! String ||
            !(Uri.tryParse(assessment['sourceRef'] as String)?.scheme == 'https' &&
              (Uri.tryParse(assessment['sourceRef'] as String)?.host.isNotEmpty ?? false) &&
              Uri.tryParse(assessment['sourceRef'] as String)?.userInfo.isEmpty == true)) {
          throw const FormatException('Referencia Investors inválida.');
        }
        final published = assessment['publishedAt'] is String ? DateTime.tryParse(assessment['publishedAt'] as String) : null;
        final available = assessment['availableAt'] is String ? DateTime.tryParse(assessment['availableAt'] as String) : null;
        final generated = assessment['generatedAt'] is String ? DateTime.tryParse(assessment['generatedAt'] as String) : null;
        if (published == null || available == null || generated == null ||
            !published.isUtc || !available.isUtc || !generated.isUtc ||
            published.isAfter(available) || available.isAfter(generated) || generated.isAfter(entry.asOf) ||
            bindings.where((binding) => binding is Map &&
              binding['evidenceId'] == assessment['evidenceId'] &&
              binding['sourceRef'] == assessment['sourceRef'] &&
              binding['assessmentFingerprint'] == assessment['assessmentFingerprint']).length != 1) {
          throw const FormatException('Temporalidad o vínculo Investors inválido.');
        }
        summaries.add('${assessment['summary']}\nFuente: ${assessment['sourceRef']} · '
          'Publicación: ${published.toIso8601String()} · Disponible: ${available.toIso8601String()}');
      }
      if (bindings.length != assessments.length) {
        throw const FormatException('Bindings Investors incompatibles.');
      }
      summary = summaries.join('\n\n');
    } else {
      summary = synthesis['summary'];
    }
    if (summary is! String || summary.trim().isEmpty || summary.length > 12000) {
      throw const FormatException('Resumen de síntesis inválido.');
    }
    return PrivateResearchSynthesis(
      kind: investors ? 'Investors' : athena ? 'ATHENA' : 'News', summary: summary,
      cycleHash: entry.cycleHash, asOf: entry.asOf,
    );
  }

  void dispose() {
    if (_ownsClient) _client.close();
  }
}

class PrivateResearchEntry {
  const PrivateResearchEntry({required this.cycleHash, required this.symbol, required this.asOf});
  final String cycleHash;
  final String symbol;
  final DateTime asOf;
}

class PrivateResearchPage {
  const PrivateResearchPage(this.items);
  final List<PrivateResearchEntry> items;
}

/// Minimal verified display model; raw private thesis is not exposed in UI.
class PrivateResearchCycleDetail {
  const PrivateResearchCycleDetail({required this.symbol, required this.cycleHash, required this.asOf, this.evidence = const []});
  final String symbol;
  final String cycleHash;
  final DateTime asOf;
  final List<PrivateResearchEvidence> evidence;
}

/// Immutable display of a canonical reference; source truth is not attested.
class PrivateResearchEvidence {
  const PrivateResearchEvidence({required this.id, required this.category,
    required this.summary, required this.source, required this.sourceRef,
    required this.availableAt, this.publishedAt});
  final String id;
  final String category;
  final String summary;
  final String source;
  final String sourceRef;
  final DateTime availableAt;
  final DateTime? publishedAt;
}

/// Verified canonical binding, not verified execution of the language model.
class PrivateResearchSynthesis {
  const PrivateResearchSynthesis({required this.kind, required this.summary, required this.cycleHash, required this.asOf});
  final String kind;
  final String summary;
  final String cycleHash;
  final DateTime asOf;
}
