import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../auth/services/auth_session.dart';
import '../models/user_personalization.dart';
import '../models/user_preferences.dart';

class UserPreferencesSessionRejectedException implements Exception {
  const UserPreferencesSessionRejectedException(this.statusCode);

  final int statusCode;

  @override
  String toString() => 'La sesión ATHENA ya no está autorizada.';
}

class UserPreferencesAuthorityChangedException implements Exception {
  const UserPreferencesAuthorityChangedException();

  @override
  String toString() => 'La autoridad ATHENA cambió durante la operación.';
}

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
  int? _lastRejectedStatusCode;

  Future<UserPreferences?> load() async {
    final token = _authenticatedToken();
    final response = await _client.get(
      Uri.parse('$_baseUrl/api/v1/user/profile/preferences'),
      headers: _authenticatedHeaders(token),
    );
    await _rejectInvalidSession(response, token);
    _requireCurrentToken(token);
    final payload = _decodeObject(response);
    final status = payload['status'];
    if (status == 'not_configured') {
      if (payload['data'] != null) {
        throw const FormatException(
          'Preferencias no configuradas con datos inesperados.',
        );
      }
      return null;
    }
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

  Future<UserPersonalization?> loadPersonalization() async {
    final token = _authenticatedToken();
    final response = await _client.get(
      Uri.parse('$_baseUrl/api/v1/user/profile/personalization'),
      headers: _authenticatedHeaders(token),
    );
    await _rejectInvalidSession(response, token);
    _requireCurrentToken(token);
    final payload = _decodeObject(response);
    final status = payload['status'];
    if (status == 'not_configured') {
      if (payload['data'] != null) {
        throw const FormatException(
          'Personalización no configurada con datos inesperados.',
        );
      }
      return null;
    }
    if (status != 'configured') {
      throw const FormatException('Estado de personalización no válido.');
    }
    final data = payload['data'];
    if (data is! Map<String, dynamic>) {
      throw const FormatException('Respuesta de personalización sin data válida.');
    }
    return UserPersonalization.fromJson(data);
  }

  Future<UserPreferences> save(UserPreferences preferences) async {
    final token = _authenticatedToken();
    final response = await _client.put(
      Uri.parse('$_baseUrl/api/v1/user/profile/preferences'),
      headers: _authenticatedHeaders(token, json: true),
      body: jsonEncode(preferences.toJson()),
    );
    await _rejectInvalidSession(response, token);
    _requireCurrentToken(token);
    final payload = _decodeObject(response);
    if (payload['status'] != 'configured') {
      throw const FormatException('Estado de preferencias persistidas no válido.');
    }
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
    final token = _authenticatedToken();
    final response = await _client.delete(
      Uri.parse('$_baseUrl/api/v1/user/profile/preferences'),
      headers: _authenticatedHeaders(token),
    );
    await _rejectInvalidSession(response, token);
    _requireCurrentToken(token);
    if (response.statusCode != 204) {
      throw StateError(_errorMessage(response));
    }
  }

  String _authenticatedToken() {
    final token = _session.accessToken?.trim();
    if (!_session.isAuthenticated || token == null || token.isEmpty) {
      final rejectedStatus = _lastRejectedStatusCode;
      if (rejectedStatus != null) {
        throw UserPreferencesSessionRejectedException(rejectedStatus);
      }
      throw StateError('Se requiere una sesión ATHENA autenticada.');
    }
    return token;
  }

  Map<String, String> _authenticatedHeaders(
    String token, {
    bool json = false,
  }) {
    return {
      'Authorization': 'Bearer $token',
      if (json) 'Content-Type': 'application/json',
    };
  }

  Future<void> _rejectInvalidSession(
    http.Response response,
    String requestToken,
  ) async {
    if (response.statusCode != 401 && response.statusCode != 403) return;
    _lastRejectedStatusCode = response.statusCode;
    await _session.clearAfterRemoteInvalidationIfCurrent(requestToken);
    throw UserPreferencesSessionRejectedException(response.statusCode);
  }

  void _requireCurrentToken(String requestToken) {
    final currentToken = _session.accessToken?.trim();
    if (!_session.isAuthenticated || currentToken != requestToken) {
      throw const UserPreferencesAuthorityChangedException();
    }
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