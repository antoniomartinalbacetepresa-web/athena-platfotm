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
    final response = await _client.get(uri, headers: {'Authorization': 'Bearer $token'});
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
