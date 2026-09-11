import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/auth_account.dart';

class AuthSessionRejectedException implements Exception {
  const AuthSessionRejectedException(this.statusCode);

  final int statusCode;

  @override
  String toString() => 'AuthSessionRejectedException($statusCode)';
}

class AthenaAuthService {
  static const String defaultBackendUrl = String.fromEnvironment(
    'ATHENA_BACKEND_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );

  AthenaAuthService({
    this.baseUrl = defaultBackendUrl,
    http.Client? client,
  }) : client = client ?? http.Client();

  final String baseUrl;
  final http.Client client;

  Future<AuthAccount> register({
    required String email,
    required String password,
    String? displayName,
  }) async {
    final normalizedEmail = email.trim();
    final normalizedDisplayName = displayName?.trim();
    if (normalizedEmail.isEmpty || password.isEmpty) {
      throw ArgumentError('Email y contraseña son obligatorios.');
    }
    if (password.length < 12) {
      throw ArgumentError('La contraseña debe tener al menos 12 caracteres.');
    }
    final response = await client.post(
      Uri.parse('$baseUrl/api/v1/auth/register'),
      headers: const {'Content-Type': 'application/json'},
      body: jsonEncode({
        'email': normalizedEmail,
        'password': password,
        if (normalizedDisplayName != null && normalizedDisplayName.isNotEmpty)
          'displayName': normalizedDisplayName,
      }),
    );
    if (response.statusCode != 201) {
      throw Exception('No se pudo crear la cuenta (${response.statusCode}).');
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map || decoded['status'] != 'account_created') {
      throw const FormatException('Respuesta de registro no válida.');
    }
    final account = decoded['account'];
    if (account is! Map) {
      throw const FormatException('Cuenta registrada ausente.');
    }
    return AuthAccount.fromMap(Map<String, dynamic>.from(account));
  }

  Future<String> login({required String email, required String password}) async {
    final normalizedEmail = email.trim();
    if (normalizedEmail.isEmpty || password.isEmpty) {
      throw ArgumentError('Email y contraseña son obligatorios.');
    }
    final response = await client.post(
      Uri.parse('$baseUrl/api/v1/auth/token'),
      headers: const {'Content-Type': 'application/x-www-form-urlencoded'},
      body: {'username': normalizedEmail, 'password': password},
    );
    if (response.statusCode != 200) {
      throw Exception('No se pudo iniciar sesión (${response.statusCode}).');
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map || decoded['token_type'] != 'bearer') {
      throw const FormatException('Respuesta de autenticación no válida.');
    }
    final token = '${decoded['access_token'] ?? ''}'.trim();
    if (token.isEmpty) {
      throw const FormatException('El backend no devolvió un token válido.');
    }
    return token;
  }

  Future<void> requestPasswordRecovery({required String email}) async {
    final normalizedEmail = email.trim();
    if (normalizedEmail.length < 3 || normalizedEmail.length > 254) {
      throw ArgumentError('Email de recuperación no válido.');
    }
    final response = await client.post(
      Uri.parse('$baseUrl/api/v1/auth/recovery/request'),
      headers: const {'Content-Type': 'application/json'},
      body: jsonEncode({'email': normalizedEmail}),
    );
    if (response.statusCode != 202) {
      throw Exception(
        'No se pudo solicitar la recuperación (${response.statusCode}).',
      );
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map || decoded['status'] != 'recovery_requested') {
      throw const FormatException('Respuesta de recuperación no válida.');
    }
  }

  Future<void> resetPassword({
    required String token,
    required String newPassword,
  }) async {
    final normalizedToken = token.trim();
    if (normalizedToken.length < 32 || normalizedToken.length > 512) {
      throw ArgumentError('Token de recuperación no válido.');
    }
    if (newPassword.length < 12 || newPassword.length > 256) {
      throw ArgumentError(
        'La nueva contraseña debe tener entre 12 y 256 caracteres.',
      );
    }
    if (newPassword.trim() != newPassword) {
      throw ArgumentError(
        'La nueva contraseña no puede empezar ni terminar con espacios.',
      );
    }
    final response = await client.post(
      Uri.parse('$baseUrl/api/v1/auth/recovery/reset'),
      headers: const {'Content-Type': 'application/json'},
      body: jsonEncode({
        'token': normalizedToken,
        'newPassword': newPassword,
      }),
    );
    if (response.statusCode != 204) {
      throw Exception(
        'No se pudo restablecer la contraseña (${response.statusCode}).',
      );
    }
  }

  Future<AuthAccount> getMe(String token) async {
    final normalizedToken = token.trim();
    if (normalizedToken.isEmpty) {
      throw ArgumentError('Token obligatorio.');
    }
    final response = await client.get(
      Uri.parse('$baseUrl/api/v1/auth/me'),
      headers: {'Authorization': 'Bearer $normalizedToken'},
    );
    if (response.statusCode == 401 || response.statusCode == 403) {
      throw AuthSessionRejectedException(response.statusCode);
    }
    if (response.statusCode != 200) {
      throw Exception('No se pudo validar la sesión (${response.statusCode}).');
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map || decoded['status'] != 'authenticated') {
      throw const FormatException('Respuesta de perfil autenticado no válida.');
    }
    final account = decoded['account'];
    if (account is! Map) {
      throw const FormatException('Cuenta autenticada ausente.');
    }
    return AuthAccount.fromMap(Map<String, dynamic>.from(account));
  }

  Future<void> changePassword({
    required String token,
    required String currentPassword,
    required String newPassword,
  }) async {
    final normalizedToken = token.trim();
    if (normalizedToken.isEmpty) {
      throw ArgumentError('Token obligatorio.');
    }
    if (currentPassword.isEmpty) {
      throw ArgumentError('La contraseña actual es obligatoria.');
    }
    if (newPassword.length < 12) {
      throw ArgumentError('La nueva contraseña debe tener al menos 12 caracteres.');
    }
    final response = await client.post(
      Uri.parse('$baseUrl/api/v1/auth/change-password'),
      headers: {
        'Authorization': 'Bearer $normalizedToken',
        'Content-Type': 'application/json',
      },
      body: jsonEncode({
        'currentPassword': currentPassword,
        'newPassword': newPassword,
      }),
    );
    if (response.statusCode != 204) {
      throw Exception('No se pudo cambiar la contraseña (${response.statusCode}).');
    }
  }

  Future<void> logout(String token) async {
    await _revoke(token, path: '/api/v1/auth/logout');
  }

  Future<void> logoutAll(String token) async {
    await _revoke(token, path: '/api/v1/auth/logout-all');
  }

  Future<void> _revoke(String token, {required String path}) async {
    final normalizedToken = token.trim();
    if (normalizedToken.isEmpty) {
      throw ArgumentError('Token obligatorio.');
    }
    final response = await client.post(
      Uri.parse('$baseUrl$path'),
      headers: {'Authorization': 'Bearer $normalizedToken'},
    );
    if (response.statusCode != 204) {
      throw Exception('No se pudo revocar la sesión (${response.statusCode}).');
    }
  }

  void dispose() => client.close();
}
