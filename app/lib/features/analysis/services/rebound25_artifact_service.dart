import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import '../../auth/services/auth_session.dart';
import 'rebound25_research_service.dart';

const rebound25ServerFixtureId = 'synthetic-rebound25-demo-v1';
final _artifactHashPattern = RegExp(r'^[a-f0-9]{64}$');

class Rebound25ArtifactEntry {
  const Rebound25ArtifactEntry({
    required this.artifactHash,
    required this.createdAt,
  });
  final String artifactHash;
  final DateTime createdAt;
}

/// Stored artificial calculation; createdAt is availability, not simulated asOf.
class Rebound25Artifact extends Rebound25ArtifactEntry {
  const Rebound25Artifact({
    required super.artifactHash,
    required super.createdAt,
    required this.result,
  });
  final Rebound25ResearchResult result;
}

class Rebound25ArtifactService {
  Rebound25ArtifactService({
    String baseUrl = const String.fromEnvironment(
      'ATHENA_BACKEND_URL',
      defaultValue: 'http://127.0.0.1:8000',
    ),
    http.Client? client,
    AuthSession? session,
    this.timeout = const Duration(seconds: 15),
  }) : _baseUrl = _origin(baseUrl),
       _client = client ?? http.Client(),
       _ownsClient = client == null,
       _session = session ?? AuthSession.instance {
    if (timeout <= Duration.zero) {
      throw ArgumentError('Timeout inválido.');
    }
  }

  final String _baseUrl;
  final http.Client _client;
  final bool _ownsClient;
  final AuthSession _session;
  final Duration timeout;
  static const maxResponseBytes = 512 * 1024;
  final _snapshots = Expando<String>();
  final _pending = <String, Future<Rebound25Artifact>>{};
  bool _disposed = false;

  static String _origin(String text) {
    final uri = Uri.tryParse(text);
    if (uri == null ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment ||
        !(uri.scheme == 'https' ||
            (uri.scheme == 'http' &&
                const {'127.0.0.1', 'localhost', '::1'}.contains(uri.host)))) {
      throw ArgumentError('Origen de backend no válido.');
    }
    return text.replaceAll(RegExp(r'/+$'), '');
  }

  void _authority(String token, int version) {
    if (_disposed ||
        !_session.isAuthenticated ||
        _session.accessToken != token ||
        _session.authorityVersion != version) {
      throw StateError('La sesión cambió durante la consulta de simulaciones.');
    }
  }

  Future<Map<String, dynamic>> _send(
    String method,
    String suffix, {
    String? body,
  }) async {
    final token = _session.accessToken;
    final version = _session.authorityVersion;
    if (_disposed ||
        !_session.isAuthenticated ||
        token == null ||
        token.trim().isEmpty) {
      throw StateError('Inicia sesión para consultar simulaciones privadas.');
    }
    Future<Map<String, dynamic>> operation() async {
      final request =
          http.Request(
              method,
              Uri.parse(
                '$_baseUrl/api/v1/research/strategies/rebound25/artifacts$suffix',
              ),
            )
            ..followRedirects = false
            ..headers['Authorization'] = 'Bearer $token';
      if (body != null) {
        request.headers['Content-Type'] = 'application/json';
        request.body = body;
      }
      final response = await _client.send(request);
      _authority(token, version);
      final bytes = BytesBuilder(copy: false);
      await for (final chunk in response.stream) {
        _authority(token, version);
        if (bytes.length + chunk.length > maxResponseBytes) {
          throw const FormatException(
            'Respuesta de simulación demasiado grande.',
          );
        }
        bytes.add(chunk);
      }
      _authority(token, version);
      if (response.statusCode != 200) {
        throw StateError('Simulación privada no disponible para esta cuenta.');
      }
      final decoded = jsonDecode(utf8.decode(bytes.takeBytes()));
      if (decoded is! Map<String, dynamic> ||
          decoded['data'] is! Map<String, dynamic>) {
        throw const FormatException('Respuesta privada inválida.');
      }
      final data = decoded['data'] as Map<String, dynamic>;
      _flags(data);
      return data;
    }

    final data = await operation().timeout(timeout);
    _authority(token, version);
    return data;
  }

  static void _flags(Map<String, dynamic> data) {
    if (data['ownerBindingVerified'] != true ||
        data['evidenceKind'] != 'synthetic_fixture' ||
        data['automaticTrading'] != false ||
        data['ordersEnabled'] != false ||
        data['productionEligible'] != false ||
        data['licenseVerified'] != false ||
        data['outOfSampleValidated'] != false) {
      throw const FormatException(
        'El artefacto perdió sus límites sintéticos.',
      );
    }
  }

  static Rebound25ArtifactEntry _entry(Map<String, dynamic> data) {
    final hash = data['artifactHash'];
    final createdText = data['createdAt'];
    final explicit =
        createdText is String &&
        RegExp(
          r'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)$',
        ).hasMatch(createdText);
    final created = data['createdAt'] is String
        ? DateTime.tryParse(data['createdAt'] as String)
        : null;
    if (data['fixtureId'] != rebound25ServerFixtureId ||
        hash is! String ||
        !_artifactHashPattern.hasMatch(hash) ||
        created == null ||
        !created.isUtc ||
        !explicit ||
        created.isAfter(DateTime.now().toUtc()) ||
        created.toIso8601String().substring(0, 19) !=
            (createdText as String).substring(0, 19)) {
      throw const FormatException('Identidad de simulación inválida.');
    }
    return Rebound25ArtifactEntry(artifactHash: hash, createdAt: created);
  }

  static Rebound25Artifact _detail(Map<String, dynamic> data) {
    final entry = _entry(data);
    final request = data['request'];
    final rawResult = data['result'];
    if (data['serverFixtureGenerated'] != true ||
        request is! Map<String, dynamic> ||
        rawResult is! Map<String, dynamic> ||
        request['instrumentId'] != 'SYNTHETIC-LAB-25' ||
        request['currency'] != 'USD' ||
        request['bars'] is! List ||
        (request['bars'] as List).length != 40) {
      throw const FormatException(
        'La simulación no procede de la plantilla del servidor.',
      );
    }
    final result = Rebound25ResearchResult.fromJson(
      rawResult,
      request: request,
    );
    if (entry.createdAt.isBefore(DateTime.parse(rawResult['asOf'] as String))) {
      throw const FormatException('Disponibilidad del artefacto incoherente.');
    }
    return Rebound25Artifact(
      artifactHash: entry.artifactHash,
      createdAt: entry.createdAt,
      result: result,
    );
  }

  Future<Rebound25Artifact> save(
    Map<String, dynamic> researchRequest, {
    required String expectedResultFingerprint,
  }) {
    if (!_session.isAuthenticated || _disposed) {
      return Future.error(StateError('Se requiere autenticación.'));
    }
    if (!_artifactHashPattern.hasMatch(expectedResultFingerprint)) {
      return Future.error(
        const FormatException('Huella del resultado inválida.'),
      );
    }
    final String body;
    try {
      body = _snapshots[researchRequest] ??= jsonEncode({
        'fixtureId': rebound25ServerFixtureId,
        'parameters': researchRequest['parameters'],
      });
      if (utf8.encode(body).length > 16 * 1024) throw const FormatException();
    } catch (_) {
      return Future.error(
        const FormatException('Parámetros de guardado inválidos.'),
      );
    }
    final version = _session.authorityVersion;
    final key = '$version:$expectedResultFingerprint:$body';
    final existing = _pending[key];
    if (existing != null) return existing;
    final future = _save(body, expectedResultFingerprint, version);
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

  Future<Rebound25Artifact> _save(
    String body,
    String expected,
    int version,
  ) async {
    final artifact = _detail(await _send('POST', '', body: body));
    if (artifact.result.resultFingerprint != expected ||
        _session.authorityVersion != version) {
      throw const FormatException(
        'El cálculo guardado no coincide con el resultado revisado.',
      );
    }
    final recovered = await get(artifact.artifactHash);
    if (recovered.result.resultFingerprint != expected ||
        recovered.createdAt != artifact.createdAt ||
        _session.authorityVersion != version) {
      throw const FormatException(
        'No se pudo verificar la recuperación privada.',
      );
    }
    return recovered;
  }

  Future<Rebound25Artifact> get(String hash) async {
    if (!_artifactHashPattern.hasMatch(hash)) {
      throw const FormatException('Hash de artefacto inválido.');
    }
    final artifact = _detail(await _send('GET', '/$hash'));
    if (artifact.artifactHash != hash) {
      throw const FormatException('Artefacto privado incompatible.');
    }
    return artifact;
  }

  Future<List<Rebound25ArtifactEntry>> list() async {
    final data = await _send('GET', '?limit=20');
    final rows = data['items'];
    if (data['metadataOnly'] != true ||
        data['readOnly'] != true ||
        rows is! List ||
        rows.length > 20 ||
        data['returnedCount'] != rows.length) {
      throw const FormatException('Índice de simulaciones inválido.');
    }
    final seen = <String>{};
    return List.unmodifiable(
      rows.map((value) {
        if (value is! Map<String, dynamic>) {
          throw const FormatException('Entrada privada inválida.');
        }
        final entry = _entry(value);
        if (!seen.add(entry.artifactHash)) {
          throw const FormatException('Artefacto duplicado.');
        }
        return entry;
      }),
    );
  }

  void dispose() {
    _disposed = true;
    if (_ownsClient) _client.close();
  }
}
