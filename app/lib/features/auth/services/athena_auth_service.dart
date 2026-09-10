import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/auth_account.dart';

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
    if (decoded is! Map || decoded['status'] != 'registered') {
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

  Future<AuthAccount> getMe(String token) async {
    final normalizedToken = token.trim();
    if (normalizedToken.isEmpty) {
      throw ArgumentError('Token obligatorio.');
    }
    final response = await client.get(
      Uri.parse('$baseUrl/api/v1/auth/me'),
      headers: {'Authorization': 'Bearer $normalizedToken'},
    );
    if (response.statusCode != 200) {
      throw Exception('Sesión no válida (${response.statusCode}).');
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

  void dispose() => client.close();
}
