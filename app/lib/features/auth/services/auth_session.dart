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
    // A logout or account switch can happen while secure storage is writing.
    // A late completion must not resurrect the superseded account in memory.
    final writeAuthorityVersion = _authorityVersion;
    await _tokenStore.writeAccessToken(token);
    if (_authorityVersion != writeAuthorityVersion) {
      // A late write may have replaced the newer owner's durable credential.
      // Repair the currently authoritative token instead of deleting it.
      // Authority may change again while the repair itself is awaiting I/O.
      // Reconcile against the latest authority until a complete operation
      // finishes without another transition.
      while (true) {
        final repairVersion = _authorityVersion;
        try {
          if (isAuthenticated) {
            await _tokenStore.writeAccessToken(_accessToken!);
          } else {
            await _tokenStore.deleteAccessToken();
          }
        } catch (_) {
          // If repair fails, never continue exposing the same authority as
          // reliably persisted. Do not revoke an even newer account.
          if (_authorityVersion == repairVersion) {
            _clearMemory();
          }
          rethrow;
        }
        if (_authorityVersion == repairVersion) {
          break;
        }
      }
      throw StateError('La sesión cambió durante el inicio de sesión.');
    }
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
    _clearMemory();
    await _tokenStore.deleteAccessToken();
  }

  Future<bool> clearAfterRemoteInvalidation() async {
    _clearMemory();
    try {
      await _tokenStore.deleteAccessToken();
      return true;
    } catch (_) {
      return false;
    }
  }

  /// Applies a remote 401/403 only to the credential that actually received it.
  /// A late response from an older owner must never revoke a replacement owner.
  Future<bool> clearAfterRemoteInvalidationIfCurrent(
    String expectedAccessToken,
  ) async {
    final expected = expectedAccessToken.trim();
    if (expected.isEmpty || !isAuthenticated || _accessToken != expected) {
      return false;
    }
    return clearAfterRemoteInvalidation();
  }

  void clear() {
    _clearMemory();
    unawaited(_tokenStore.deleteAccessToken().catchError((Object _) {}));
  }

  void _clearMemory() {
    final changed = _accessToken != null || _account != null;
    _accessToken = null;
    _account = null;
    // A clear is an authority transition even if memory was already empty.
    // Otherwise a pending restore can resurrect a session after logout.
    _authorityVersion += 1;
    if (changed) {
      notifyListeners();
    }
  }
}