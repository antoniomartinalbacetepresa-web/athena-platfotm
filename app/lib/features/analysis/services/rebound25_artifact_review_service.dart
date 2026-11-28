import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import '../../auth/services/auth_session.dart';
import 'private_research_history_service.dart';
import 'rebound25_artifact_service.dart';

/// Frozen human review of a calculation available at createdAt, not series time.
class Rebound25ArtifactReviewDraft {
  Rebound25ArtifactReviewDraft({
    required this.artifact,
    required String thesis,
    required String objection,
    required DateTime authoredAt,
  }) : thesis = thesis.trim(),
       objection = objection.trim(),
       asOf = authoredAt {
    if (!RegExp(r'^[a-f0-9]{64}$').hasMatch(artifact.artifactHash) ||
        !artifact.createdAt.isUtc ||
        artifact.createdAt.isAfter(DateTime.now().toUtc()) ||
        this.thesis.isEmpty ||
        this.thesis.length > 4000 ||
        objection.trim().isEmpty ||
        objection.length > 4000 ||
        !authoredAt.isUtc ||
        authoredAt.isBefore(artifact.createdAt) ||
        authoredAt.isAfter(DateTime.now().toUtc())) {
      throw const FormatException('Revisión de simulación inválida.');
    }
    journalId =
        'backtest-${artifact.artifactHash.substring(0, 16)}-${authoredAt.microsecondsSinceEpoch}';
    final stamp = authoredAt.toIso8601String();
    encodedBody = jsonEncode({
      'journalId': journalId,
      'revisionId': 'r1',
      'thesis': this.thesis,
      'recordedAt': stamp,
      'asOf': stamp,
      'journalReferences': [
        {
          'referenceId': 'human-question',
          'kind': 'assumption',
          'availableAt': stamp,
          'source': 'human_research',
          'sourceRef': 'urn:human:backtest-question',
        },
      ],
      'contradictoryEvidence': [
        {
          'evidenceId': 'human-objection',
          'kind': 'alternative_explanation',
          'claim': objection.trim(),
          'strength': 'material',
          'availableAt': stamp,
          'source': 'human_research',
          'sourceRef': 'urn:human:backtest-objection',
        },
      ],
    });
  }
  final Rebound25Artifact artifact;
  final String thesis;
  final String objection;
  final DateTime asOf;
  late final String journalId;
  late final String encodedBody;
}

class Rebound25ArtifactReviewService {
  Rebound25ArtifactReviewService({
    String baseUrl = const String.fromEnvironment(
      'ATHENA_BACKEND_URL',
      defaultValue: 'http://127.0.0.1:8000',
    ),
    http.Client? client,
    AuthSession? session,
  }) : _baseUrl = _origin(baseUrl),
       _client = client ?? http.Client(),
       _ownsClient = client == null,
       _session = session ?? AuthSession.instance;
  static String _origin(String value) {
    final uri = Uri.tryParse(value);
    if (uri == null ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment ||
        !(uri.scheme == 'https' ||
            (uri.scheme == 'http' &&
                const {'127.0.0.1', 'localhost', '::1'}.contains(uri.host)))) {
      throw ArgumentError('Origen de backend inválido.');
    }
    return value.replaceAll(RegExp(r'/+$'), '');
  }

  bool _disposed = false;
  final String _baseUrl;
  final http.Client _client;
  final bool _ownsClient;
  final AuthSession _session;
  final _pending = <String, Future<PrivateResearchCycleDetail>>{};
  Future<PrivateResearchCycleDetail> create(
    Rebound25ArtifactReviewDraft draft,
  ) {
    if (_disposed) {
      return Future.error(StateError('Servicio de revisión cerrado.'));
    }
    final key =
        '${_session.authorityVersion}:${draft.artifact.artifactHash}:${draft.encodedBody}';
    final previous = _pending[key];
    if (previous != null) {
      return previous;
    }
    final future = _create(draft);
    _pending[key] = future;
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
    Rebound25ArtifactReviewDraft draft,
  ) async {
    final token = _session.accessToken, version = _session.authorityVersion;
    if (_disposed ||
        !_session.isAuthenticated ||
        token == null ||
        token.trim().isEmpty) {
      throw StateError('Inicia sesión para revisar la simulación.');
    }
    void check() {
      if (_disposed ||
          !_session.isAuthenticated ||
          _session.accessToken != token ||
          _session.authorityVersion != version) {
        throw StateError('La sesión cambió durante la revisión.');
      }
    }

    Future<dynamic> send() async {
      final request =
          http.Request(
              'POST',
              Uri.parse(
                '$_baseUrl/api/v1/research/strategies/rebound25/artifacts/'
                '${draft.artifact.artifactHash}/research-cycle',
              ),
            )
            ..followRedirects = false
            ..headers.addAll({
              'Authorization': 'Bearer $token',
              'Content-Type': 'application/json',
            })
            ..body = draft.encodedBody;
      final response = await _client.send(request);
      check();
      if (response.statusCode != 200) {
        throw StateError(
          'Revisión privada no disponible; conserva el borrador para reintentar.',
        );
      }
      final bytes = BytesBuilder(copy: false);
      await for (final chunk in response.stream) {
        check();
        if (bytes.length + chunk.length >
            PrivateResearchHistoryService.maxResponseBytes) {
          throw const FormatException('Respuesta demasiado grande.');
        }
        bytes.add(chunk);
      }
      check();
      return jsonDecode(utf8.decode(bytes.takeBytes()));
    }

    final decoded = await send().timeout(
      PrivateResearchHistoryService.requestTimeout,
    );
    check();
    if (decoded is! Map<String, dynamic> ||
        decoded['data'] is! Map<String, dynamic>) {
      throw const FormatException('Revisión inválida.');
    }
    final data = decoded['data'] as Map<String, dynamic>;
    final integrity = data['integrity'],
        policy = data['policy'],
        ref = data['syntheticBacktestReference'];
    final hash = integrity is Map ? integrity['cycleHash'] : null;
    final expectedRef =
        'urn:athena:synthetic-backtest:${draft.artifact.artifactHash}';
    final availability = ref is Map && ref['availableAt'] is String
        ? DateTime.tryParse(ref['availableAt'] as String)
        : null;
    final cutoff = data['asOf'] is String
        ? DateTime.tryParse(data['asOf'] as String)
        : null;
    if (hash is! String ||
        !RegExp(r'^[a-f0-9]{64}$').hasMatch(hash) ||
        integrity is! Map ||
        integrity['algorithm'] != 'sha256' ||
        data['symbol'] != 'SYNTH' ||
        data['instrumentId'] != draft.artifact.result.instrumentId ||
        cutoff == null ||
        !cutoff.isUtc ||
        !cutoff.isAtSameMomentAs(draft.asOf) ||
        data['advisoryStatus'] != 'no_advice' ||
        data['productionEligible'] != false ||
        data['isWeightingReady'] != false ||
        policy is! Map ||
        policy['automaticTrading'] != false ||
        policy['automaticProductionPromotion'] != false ||
        ref is! Map ||
        ref['artifactHash'] != draft.artifact.artifactHash ||
        ref['sourceRef'] != expectedRef ||
        ref['resultFingerprint'] != draft.artifact.result.resultFingerprint ||
        ref['serverFixtureGenerated'] != true ||
        ref['listingIdentityVerified'] != false ||
        ref['productionEligible'] != false ||
        ref['automaticTrading'] != false ||
        availability == null ||
        !availability.isUtc ||
        !availability.isAtSameMomentAs(draft.artifact.createdAt)) {
      throw const FormatException(
        'Identidad o disponibilidad de cálculo incompatible.',
      );
    }
    final reader = PrivateResearchHistoryService(
      baseUrl: _baseUrl,
      client: _ReviewReadClient(_client, check),
      session: _session,
    );
    final detail = await reader.loadCycleWithBinding(
      PrivateResearchEntry(cycleHash: hash, symbol: 'SYNTH', asOf: draft.asOf),
      validatePackage: (package) {
        final cycle = package['cycle'] as Map<String, dynamic>,
            journal = package['journal'],
            radar = package['radar'];
        final expectedJournal =
            '__athena_private_owner_${_session.account!.id}__:${draft.journalId}';
        if (cycle['instrumentId'] != draft.artifact.result.instrumentId ||
            journal is! Map ||
            journal['journalId'] != expectedJournal ||
            journal['revisionId'] != 'r1' ||
            journal['thesis'] != draft.thesis ||
            radar is! Map ||
            radar['candidates'] is! List ||
            (radar['candidates'] as List).length != 1) {
          throw const FormatException(
            'La investigación no corresponde al borrador.',
          );
        }
        final review = package['devilsAdvocate'];
        final objections = review is Map ? review['evidence'] : null;
        if (objections is! List ||
            objections
                    .where(
                      (row) =>
                          row is Map &&
                          row['evidenceId'] == 'human-objection' &&
                          row['claim'] == draft.objection &&
                          row['sourceRef'] == 'urn:human:backtest-objection',
                    )
                    .length !=
                1) {
          throw const FormatException('Objeción humana no vinculada.');
        }
        final candidate = (radar['candidates'] as List).single;
        if (candidate is! Map) {
          throw const FormatException('Radar inválido.');
        }
        for (final rows in [journal['references'], candidate['evidence']]) {
          if (rows is! List ||
              rows
                      .where(
                        (row) =>
                            row is Map &&
                            row['sourceRef'] == expectedRef &&
                            row['availableAt'] is String &&
                            DateTime.tryParse(
                                  row['availableAt'] as String,
                                )?.isAtSameMomentAs(draft.artifact.createdAt) ==
                                true,
                      )
                      .length !=
                  1) {
            throw const FormatException('Referencia de cálculo no vinculada.');
          }
        }
      },
    );
    check();
    return detail;
  }

  void dispose() {
    _disposed = true;
    if (_ownsClient) {
      _client.close();
    }
  }
}

// Keep the existing canonical package validator while bounding its private read.
class _ReviewReadClient extends http.BaseClient {
  _ReviewReadClient(this.delegate, this.check);
  final http.Client delegate;
  final void Function() check;
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    check();
    request.followRedirects = false;
    final response = await delegate.send(request);
    check();
    Stream<List<int>> bounded() async* {
      var count = 0;
      await for (final chunk in response.stream) {
        check();
        count += chunk.length;
        if (count > PrivateResearchHistoryService.maxResponseBytes) {
          throw const FormatException('Respuesta privada demasiado grande.');
        }
        yield chunk;
      }
      check();
    }

    return http.StreamedResponse(
      bounded(),
      response.statusCode,
      headers: response.headers,
      request: request,
    );
  }
}
