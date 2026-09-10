import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../auth/services/auth_session.dart';
import '../models/user_preferences.dart';

class UserPreferencesService {
  static const String _defaultBackendUrl = String.fromEnvironment(
    'ATHENA_BACKEND_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );

  UserPreferencesService({
    String baseUrl = _defaultBackendUrl,
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

  Future<UserPreferences?> load() async {
    final response = await _client.get(
      Uri.parse('$_baseUrl/api/v1/user/profile/preferences'),
      headers: _authenticatedHeaders(),
    );
    final payload = _decodeObject(response);
    final status = payload['status'];
    if (status == 'not_configured') return null;
    if (status != 'configured') {
      throw const FormatException('Estado de preferencias no válido.');
    }
    final data = payload['data'];
    if (data is! Map<String, dynamic>) {
      throw const FormatException('Respuesta de preferencias sin data válida.');
    }
    final preferences = data['preferences'];
    if (preferences is! Map<String, dynamic>) {
      throw const FormatException('Preferencias cifradas no válidas.');
    }
    return UserPreferences.fromJson(preferences);
  }

  Future<UserPreferences> save(UserPreferences preferences) async {
    final response = await _client.put(
      Uri.parse('$_baseUrl/api/v1/user/profile/preferences'),
      headers: _authenticatedHeaders(json: true),
      body: jsonEncode(preferences.toJson()),
    );
    final payload = _decodeObject(response);
    final data = payload['data'];
    if (data is! Map<String, dynamic>) {
      throw const FormatException('Respuesta de preferencias sin data válida.');
    }
    final stored = data['preferences'];
    if (stored is! Map<String, dynamic>) {
      throw const FormatException('Preferencias persistidas no válidas.');
    }
    return UserPreferences.fromJson(stored);
  }

  Future<void> delete() async {
    final response = await _client.delete(
      Uri.parse('$_baseUrl/api/v1/user/profile/preferences'),
      headers: _authenticatedHeaders(),
    );
    if (response.statusCode != 204) {
      throw StateError(_errorMessage(response));
    }
  }

  Map<String, String> _authenticatedHeaders({bool json = false}) {
    final token = _session.accessToken?.trim();
    if (!_session.isAuthenticated || token == null || token.isEmpty) {
      throw StateError('Se requiere una sesión ATHENA autenticada.');
    }
    return {
      'Authorization': 'Bearer $token',
      if (json) 'Content-Type': 'application/json',
    };
  }

  Map<String, dynamic> _decodeObject(http.Response response) {
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw StateError(_errorMessage(response));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw const FormatException('Respuesta ATHENA no válida.');
    }
    return decoded;
  }

  String _errorMessage(http.Response response) {
    try {
      final decoded = jsonDecode(response.body);
      if (decoded is Map<String, dynamic> && decoded['detail'] is String) {
        return decoded['detail'] as String;
      }
    } catch (_) {
      // Do not expose an unparsable backend body.
    }
    return 'Las preferencias de usuario no pudieron completar la operación.';
  }

  void dispose() {
    if (_ownsClient) _client.close();
  }
}
