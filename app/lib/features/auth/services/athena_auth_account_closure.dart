import 'dart:convert';

import 'athena_auth_service.dart';

class AccountClosureRejectedException implements Exception {
  const AccountClosureRejectedException(this.statusCode);

  final int statusCode;
}

extension AthenaAuthAccountClosure on AthenaAuthService {
  Future<void> closeAccount({
    required String token,
    required String currentPassword,
  }) async {
    final normalizedToken = token.trim();
    if (normalizedToken.isEmpty) {
      throw ArgumentError('Token obligatorio.');
    }
    if (currentPassword.trim().isEmpty || currentPassword.length > 256) {
      throw ArgumentError('La contraseña actual no es válida.');
    }
    final response = await client.post(
      Uri.parse('$baseUrl/api/v1/auth/close-account'),
      headers: {
        'Authorization': 'Bearer $normalizedToken',
        'Content-Type': 'application/json',
      },
      body: jsonEncode({'currentPassword': currentPassword}),
    );
    if (response.statusCode == 401 || response.statusCode == 403) {
      throw AccountClosureRejectedException(response.statusCode);
    }
    if (response.statusCode != 204) {
      throw Exception('No se pudo cerrar la cuenta (${response.statusCode}).');
    }
  }
}
