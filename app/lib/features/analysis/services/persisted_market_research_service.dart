import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../auth/services/auth_session.dart';
import 'private_research_history_service.dart';

/// A frozen human-authored request. Retrying never advances its cutoff or IDs.
class PersistedMarketResearchDraft {
  PersistedMarketResearchDraft({
    required this.instrumentId,
    required String symbol,
    required String sourceProvider,
    required DateTime observedFrom,
    required DateTime observedTo,
    required DateTime authoredAt,
    required String journalId,
    required String thesis,
    required String contradiction,
    List<String> sourceCycleHashes = const [],
  }) : symbol = symbol,
       asOf = authoredAt {
    if (instrumentId <= 0 ||
        !RegExp(r'^[A-Z0-9][A-Z0-9.-]{0,19}$').hasMatch(symbol) ||
        sourceProvider.trim().isEmpty ||
        journalId.trim().isEmpty ||
        thesis.trim().isEmpty ||
        contradiction.trim().isEmpty ||
        !observedFrom.isUtc ||
        !observedTo.isUtc ||
        !authoredAt.isUtc ||
        observedFrom.isAfter(observedTo) ||
        observedTo.isAfter(authoredAt) ||
        observedTo.difference(observedFrom) > const Duration(days: 366) ||
        authoredAt.isAfter(DateTime.now().toUtc())) {
      throw const FormatException('Borrador de investigación inválido.');
    }
    if (sourceCycleHashes.length > 5 ||
        sourceCycleHashes.any(
          (hash) => !RegExp(r'^[a-f0-9]{64}$').hasMatch(hash),
        )) {
      throw const FormatException('Hashes de ciclos privados inválidos.');
    }
    final sources = sourceCycleHashes.toSet().toList()..sort();
    this.sourceCycleHashes = List.unmodifiable(sources);
    this.journalId = journalId;
    this.thesis = thesis.trim();
    final timestamp = authoredAt.toIso8601String();
    encodedBody = jsonEncode({
      if (sources.isNotEmpty) 'sourceCycleHashes': sources,
      'instrumentId': instrumentId,
      'symbol': symbol,
      'sourceProvider': sourceProvider,
      'observedFrom': observedFrom.toIso8601String(),
      'observedTo': observedTo.toIso8601String(),
      'asOf': timestamp,
      'recordedAt': timestamp,
      'journalId': journalId,
      'revisionId': 'r1',
      'thesis': thesis.trim(),
      'limit': 200,
      'journalReferences': [
        {
          'referenceId': 'human-question',
          'kind': 'assumption',
          'availableAt': timestamp,
          'source': 'human_research',
          'sourceRef': 'urn:human:research-question',
        },
      ],
      'contradictoryEvidence': [
        {
          'evidenceId': 'human-objection',
          'kind': 'alternative_explanation',
          'claim': contradiction.trim(),
          'strength': 'material',
          'availableAt': timestamp,
          'source': 'human_research',
          'sourceRef': 'urn:human:research-objection',
        },
      ],
    });
  }
  final int instrumentId;
  late final List<String> sourceCycleHashes;
  late final String journalId;
  late final String thesis;
  final String symbol;
  final DateTime asOf;
  late final String encodedBody;
}

/// Authenticated synthetic-only bridge. No public write/read fallback.
class PersistedMarketResearchService {
  PersistedMarketResearchService({
    String baseUrl = const String.fromEnvironment(
      'ATHENA_BACKEND_URL',
      defaultValue: 'http://127.0.0.1:8000',
    ),
    http.Client? client,
    AuthSession? session,
  }) : _baseUrl = baseUrl.replaceAll(RegExp(r'/+$'), ''),
       _client = client ?? http.Client(),
       _ownsClient = client == null,
       _session = session ?? AuthSession.instance;
  final String _baseUrl;
  final http.Client _client;
  final bool _ownsClient;
  final AuthSession _session;
  final Map<String, Future<PrivateResearchCycleDetail>> _pending = {};

  Future<PrivateResearchCycleDetail> create(
    PersistedMarketResearchDraft draft,
  ) {
    final key = '${_session.authorityVersion}:${draft.encodedBody}';
    final existing = _pending[key];
    if (existing != null) return existing;
    final future = _create(draft);
    _pending[key] = future;
    // Handle cleanup without creating a second unhandled error future.
    future.then(
      (_) {
        _pending.remove(key);
      },
      onError: (Object _, StackTrace _) {
        _pending.remove(key);
      },
    );
    return future;
  }

  Future<PrivateResearchCycleDetail> _create(
    PersistedMarketResearchDraft draft,
  ) async {
    final token = _session.accessToken;
    final version = _session.authorityVersion;
    if (!_session.isAuthenticated || token == null || token.trim().isEmpty) {
      throw StateError('Inicia sesión para crear una investigación privada.');
    }
    void checkSession() {
      if (!_session.isAuthenticated ||
          _session.authorityVersion != version ||
          _session.accessToken != token) {
        throw StateError('La sesión cambió durante la investigación.');
      }
    }

    final response = await _client
        .post(
          Uri.parse(
            '$_baseUrl/api/v1/recommendations/'
            'professional-research/research-cycle/from-persisted-market-history',
          ),
          headers: {
            'Authorization': 'Bearer $token',
            'Content-Type': 'application/json',
          },
          body: draft.encodedBody,
        )
        .timeout(PrivateResearchHistoryService.requestTimeout);
    checkSession();
    if (response.statusCode != 200) {
      throw StateError(
        'No se pudo crear o recuperar la investigación privada.',
      );
    }
    if (response.bodyBytes.length >
        PrivateResearchHistoryService.maxResponseBytes) {
      throw const FormatException('Respuesta privada demasiado grande.');
    }
    final decoded = jsonDecode(utf8.decode(response.bodyBytes));
    if (decoded is! Map<String, dynamic> ||
        decoded['data'] is! Map<String, dynamic>) {
      throw const FormatException('Respuesta de creación inválida.');
    }
    final data = decoded['data'] as Map<String, dynamic>;
    final integrity = data['integrity'];
    final reference = data['marketHistoryReference'];
    final policy = data['policy'];
    final hash = integrity is Map ? integrity['cycleHash'] : null;
    final cutoff = data['asOf'] is String
        ? DateTime.tryParse(data['asOf'] as String)
        : null;
    if (hash is! String ||
        !RegExp(r'^[a-f0-9]{64}$').hasMatch(hash) ||
        integrity is! Map ||
        integrity['algorithm'] != 'sha256' ||
        data['instrumentId'] != draft.instrumentId.toString() ||
        data['symbol'] != draft.symbol ||
        cutoff == null ||
        !cutoff.isUtc ||
        !cutoff.isAtSameMomentAs(draft.asOf) ||
        data['advisoryStatus'] != 'no_advice' ||
        data['productionEligible'] != false ||
        data['isWeightingReady'] != false ||
        policy is! Map ||
        policy['automaticTrading'] != false ||
        policy['automaticProductionPromotion'] != false ||
        reference is! Map ||
        reference['evidenceKind'] != 'synthetic_fixture' ||
        reference['metadataOnly'] != true ||
        reference['licenceVerified'] != false ||
        reference['historicalPointInTimeEligible'] != false ||
        reference['productionEligible'] != false ||
        reference['automaticTrading'] != false) {
      throw const FormatException(
        'Identidad o límites del ciclo incompatibles.',
      );
    }
    final referenceHash = reference['referenceHash'];
    if (referenceHash is! String ||
        !RegExp(r'^[a-f0-9]{64}$').hasMatch(referenceHash) ||
        reference['sourceRef'] != 'urn:athena:market-history:$referenceHash') {
      throw const FormatException('Referencia sintética inválida.');
    }
    final expectedJournal =
        '__athena_private_owner_${_session.account!.id}__:${draft.journalId}';
    final reader = PrivateResearchHistoryService(
      baseUrl: _baseUrl,
      client: _client,
      session: _session,
    );
    final detail = await reader.loadCycleWithBinding(
      PrivateResearchEntry(
        cycleHash: hash,
        symbol: draft.symbol,
        asOf: draft.asOf,
      ),
      validatePackage: (package) {
        final cycle = package['cycle'] as Map<String, dynamic>;
        final journal = package['journal'];
        final radar = package['radar'];
        final cycleJournal = cycle['journal'];
        if (cycle['instrumentId'] != draft.instrumentId.toString() ||
            cycleJournal is! Map ||
            cycleJournal['journalId'] != expectedJournal ||
            cycleJournal['revisionId'] != 'r1' ||
            journal is! Map ||
            journal['journalId'] != expectedJournal ||
            journal['revisionId'] != 'r1' ||
            journal['thesis'] != draft.thesis ||
            radar is! Map) {
          throw const FormatException(
            'El ciclo privado no corresponde al borrador.',
          );
        }
        final attachedSources =
            (journal['references'] is List
                    ? journal['references'] as List
                    : const [])
                .where(
                  (item) =>
                      item is Map &&
                      item['sourceRef'] is String &&
                      (item['sourceRef'] as String).startsWith(
                        'urn:athena:research-cycle:',
                      ),
                )
                .map((item) => (item as Map)['sourceRef'] as String)
                .toList()
              ..sort();
        final expectedSources = draft.sourceCycleHashes
            .map((hash) => 'urn:athena:research-cycle:$hash')
            .toList();
        if (attachedSources.length != expectedSources.length ||
            attachedSources.join('|') != expectedSources.join('|')) {
          throw const FormatException(
            'Los ciclos origen no corresponden al borrador.',
          );
        }
        final candidates = radar['candidates'];
        if (candidates is! List ||
            candidates.length != 1 ||
            candidates.single is! Map) {
          throw const FormatException('Radar privado incompatible.');
        }
        for (final refs in [
          journal['references'],
          (candidates.single as Map)['evidence'],
        ]) {
          if (refs is! List ||
              refs
                      .where(
                        (item) =>
                            item is Map &&
                            item['sourceRef'] == reference['sourceRef'],
                      )
                      .length !=
                  1) {
            throw const FormatException(
              'La referencia de mercado no está vinculada.',
            );
          }
        }
      },
    );
    checkSession();
    return detail;
  }

  void dispose() {
    if (_ownsClient) _client.close();
  }
}
