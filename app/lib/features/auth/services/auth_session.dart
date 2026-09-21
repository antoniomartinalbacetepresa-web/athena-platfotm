import 'dart:async';

import 'package:flutter/foundation.dart';

import '../models/auth_account.dart';
import 'auth_token_store.dart';

enum AuthSessionRestoreResult {
  restored,
  noStoredToken,
  rejected,
  temporarilyUnavailable,
}

class AuthSession extends ChangeNotifier {
  AuthSession._({AuthTokenStore? tokenStore})
      : _tokenStore = tokenStore ?? SecureAuthTokenStore();

  AuthSession.forTesting(AuthTokenStore tokenStore) : _tokenStore = tokenStore;

  static final AuthSession instance = AuthSession._();

  final AuthTokenStore _tokenStore;
  String? _accessToken;
  AuthAccount? _account;
  int _authorityVersion = 0;

  String? get accessToken => _accessToken;
  AuthAccount? get account => _account;
  bool get isAuthenticated => _accessToken != null && _account != null;

  void establish({required String accessToken, required AuthAccount account}) {
    final token = accessToken.trim();
    if (token.isEmpty || !account.isActive) {
      throw ArgumentError('La sesión autenticada no es válida.');
    }
    final changed = _accessToken != token || _account != account;
    _accessToken = token;
    _account = account;
    if (changed) {
      _authorityVersion += 1;
      notifyListeners();
    }
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
    final restoreAuthorityVersion = _authorityVersion;

    final String? storedToken;
    try {
      storedToken = await _tokenStore.readAccessToken();
    } catch (_) {
      if (_authorityVersion != restoreAuthorityVersion) {
        return isAuthenticated
            ? AuthSessionRestoreResult.restored
            : AuthSessionRestoreResult.temporarilyUnavailable;
      }
      _clearMemory();
      return AuthSessionRestoreResult.temporarilyUnavailable;
    }
    if (_authorityVersion != restoreAuthorityVersion) {
      return isAuthenticated
          ? AuthSessionRestoreResult.restored
          : AuthSessionRestoreResult.temporarilyUnavailable;
    }
    if (storedToken == null) {
      _clearMemory();
      return AuthSessionRestoreResult.noStoredToken;
    }

    // Secure storage is a persistence mechanism, not an authority boundary.
    // Never send malformed/blank persisted credentials to the backend and never
    // expose them as an authenticated in-memory session. Whitespace is
    // normalized consistently with establishPersisted().
    final token = storedToken.trim();
    if (token.isEmpty) {
      _clearMemory();
      try {
        await _tokenStore.deleteAccessToken();
      } catch (_) {
        return AuthSessionRestoreResult.temporarilyUnavailable;
      }
      return AuthSessionRestoreResult.rejected;
    }

    try {
      final account = await validateToken(token);
      // Validation is tied to the authority snapshot that initiated restore.
      // A login/logout/account transition while validation is in flight wins;
      // a late persisted credential must never resurrect an older owner.
      if (_authorityVersion != restoreAuthorityVersion) {
        return isAuthenticated
            ? AuthSessionRestoreResult.restored
            : AuthSessionRestoreResult.temporarilyUnavailable;
      }
      establish(accessToken: token, account: account);
      return AuthSessionRestoreResult.restored;
    } catch (error) {
      if (_authorityVersion != restoreAuthorityVersion) {
        return isAuthenticated
            ? AuthSessionRestoreResult.restored
            : AuthSessionRestoreResult.temporarilyUnavailable;
      }
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
    // Clearing an authenticated session is an authority transition. Revoke the
    // in-memory authority first so a secure-storage outage cannot leave the UI
    // authenticated after the caller explicitly requested a local clear. If
    // deletion fails the durable credential remains stale and must be remotely
    // revalidated before any later restore can regain authority.
    _clearMemory();
    await _tokenStore.deleteAccessToken();
  }

  Future<bool> clearAfterRemoteInvalidation() async {
    // Once the server has irreversibly invalidated the credential/account, the
    // client must stop presenting an authenticated in-memory state even if the
    // platform secure-storage deletion fails. A retained token is stale and is
    // revalidated/rejected on the next restore attempt.
    _clearMemory();
    try {
      await _tokenStore.deleteAccessToken();
      return true;
    } catch (_) {
      return false;
    }
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
    final changed = _accessToken != null || _account != null;
    _accessToken = null;
    _account = null;
    if (changed) {
      _authorityVersion += 1;
      notifyListeners();
    }
  }
}
