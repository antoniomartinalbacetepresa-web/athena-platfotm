import 'package:flutter_secure_storage/flutter_secure_storage.dart';

abstract interface class AuthTokenStore {
  Future<String?> readAccessToken();
  Future<void> writeAccessToken(String token);
  Future<void> deleteAccessToken();
}

class SecureAuthTokenStore implements AuthTokenStore {
  SecureAuthTokenStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  static const String _accessTokenKey = 'athena.auth.access_token';

  final FlutterSecureStorage _storage;

  @override
  Future<String?> readAccessToken() async {
    final value = (await _storage.read(key: _accessTokenKey))?.trim();
    return value == null || value.isEmpty ? null : value;
  }

  @override
  Future<void> writeAccessToken(String token) async {
    final normalized = token.trim();
    if (normalized.isEmpty) {
      throw ArgumentError('No se puede persistir un token vacío.');
    }
    await _storage.write(key: _accessTokenKey, value: normalized);
  }

  @override
  Future<void> deleteAccessToken() => _storage.delete(key: _accessTokenKey);
}
