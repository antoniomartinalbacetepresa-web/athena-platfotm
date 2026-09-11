import 'dart:async';

import '../models/auth_account.dart';
import 'auth_token_store.dart';

enum AuthSessionRestoreResult {
  restored,
  noStoredToken,
  rejected,
  temporarilyUnavailable,
}

class AuthSession {
  AuthSession._({AuthTokenStore? tokenStore})
      : _tokenStore = tokenStore ?? SecureAuthTokenStore();

  AuthSession.forTesting(AuthTokenStore tokenStore) : _tokenStore = tokenStore;

  static final AuthSession instance = AuthSession._();

  final AuthTokenStore _tokenStore;
  String? _accessToken;
  AuthAccount? _account;

  String? get accessToken => _accessToken;
  AuthAccount? get account => _account;
  bool get isAuthenticated => _accessToken != null && _account != null;

  void establish({required String accessToken, required AuthAccount account}) {
    final token = accessToken.trim();
    if (token.isEmpty || !account.isActive) {
      throw ArgumentError('La sesión autenticada no es válida.');
    }
    _accessToken = token;
    _account = account;
  }

  Future<void> establishPersisted({
    required String accessToken,
    required AuthAccount account,
  }) async {
    final token = accessToken.trim();
    if (token.isEmpty || !account.isActive) {
      throw ArgumentError('La sesión autenticada no es válida.');
    }
    await _tokenStore.writeAccessToken(token);
    establish(accessToken: token, account: account);
  }

  Future<AuthSessionRestoreResult> restore({
    required Future<AuthAccount> Function(String token) validateToken,
    required bool Function(Object error) shouldDiscardToken,
  }) async {
    if (isAuthenticated) return AuthSessionRestoreResult.restored;

    final String? token;
    try {
      token = await _tokenStore.readAccessToken();
    } catch (_) {
      _clearMemory();
      return AuthSessionRestoreResult.temporarilyUnavailable;
    }
    if (token == null) {
      _clearMemory();
      return AuthSessionRestoreResult.noStoredToken;
    }

    try {
      final account = await validateToken(token);
      establish(accessToken: token, account: account);
      return AuthSessionRestoreResult.restored;
    } catch (error) {
      _clearMemory();
      if (!shouldDiscardToken(error)) {
        return AuthSessionRestoreResult.temporarilyUnavailable;
      }
      try {
        await _tokenStore.deleteAccessToken();
      } catch (_) {
        return AuthSessionRestoreResult.temporarilyUnavailable;
      }
      return AuthSessionRestoreResult.rejected;
    }
  }

  Future<void> clearPersisted() async {
    await _tokenStore.deleteAccessToken();
    _clearMemory();
  }

  void clear() {
    _clearMemory();
    // Existing UI call sites use a synchronous clear contract. Remove the
    // durable token as well so a local logout cannot intentionally preserve a
    // credential for the next launch. Explicit security-sensitive flows can
    // await clearPersisted() when they need deletion failure surfaced.
    unawaited(_tokenStore.deleteAccessToken().catchError((Object _) {}));
  }

  void _clearMemory() {
    _accessToken = null;
    _account = null;
  }
}
