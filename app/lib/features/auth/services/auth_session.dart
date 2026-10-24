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
  int _persistenceGeneration = 0;
  Future<void>? _pendingStorageMutation;

  // Preserve immediate secure-storage invocation when idle (including in
  // Flutter widget-test zones), while serializing overlapping mutations.
  // A delayed logout must not erase a later persisted login.
  Future<void> _mutateTokenStore(Future<void> Function() operation) {
    final previous = _pendingStorageMutation;
    final pending = previous == null
        ? operation()
        : previous.then((_) => operation());
    // A failed mutation must fail its caller without poisoning later attempts.
    final settled = pending.catchError((Object _) {});
    _pendingStorageMutation = settled;
    unawaited(settled.then((_) {
      if (identical(_pendingStorageMutation, settled)) {
        _pendingStorageMutation = null;
      }
    }));
    return pending;
  }

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
    final authorityAtStart = _authorityVersion;
    final generation = ++_persistenceGeneration;
    await _mutateTokenStore(() => _tokenStore.writeAccessToken(token));
    if (_authorityVersion != authorityAtStart ||
        _persistenceGeneration != generation) {
      throw StateError('La autoridad ATHENA cambió durante la persistencia.');
    }
    establish(accessToken: token, account: account);
  }

  Future<AuthSessionRestoreResult> restore({
    required Future<AuthAccount> Function(String token) validateToken,
    required bool Function(Object error) shouldDiscardToken,
  }) async {
    if (isAuthenticated) return AuthSessionRestoreResult.restored;
    final restoreAuthorityVersion = _authorityVersion;
    final restorePersistenceGeneration = _persistenceGeneration;
    bool restoreIsStale() =>
        _authorityVersion != restoreAuthorityVersion ||
        _persistenceGeneration != restorePersistenceGeneration;

    final String? storedToken;
    try {
      storedToken = await _tokenStore.readAccessToken();
    } catch (_) {
      if (restoreIsStale()) {
        return isAuthenticated
            ? AuthSessionRestoreResult.restored
            : AuthSessionRestoreResult.temporarilyUnavailable;
      }
      _clearMemory();
      return AuthSessionRestoreResult.temporarilyUnavailable;
    }
    if (restoreIsStale()) {
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
      ++_persistenceGeneration;
      try {
        await _mutateTokenStore(() => _tokenStore.deleteAccessToken());
      } catch (_) {
        return AuthSessionRestoreResult.temporarilyUnavailable;
      }
      return AuthSessionRestoreResult.rejected;
    }

    try {
      final account = await validateToken(token);
      if (restoreIsStale()) {
        return isAuthenticated
            ? AuthSessionRestoreResult.restored
            : AuthSessionRestoreResult.temporarilyUnavailable;
      }
      establish(accessToken: token, account: account);
      return AuthSessionRestoreResult.restored;
    } catch (error) {
      if (restoreIsStale()) {
        return isAuthenticated
            ? AuthSessionRestoreResult.restored
            : AuthSessionRestoreResult.temporarilyUnavailable;
      }
      _clearMemory();
      if (!shouldDiscardToken(error)) {
        return AuthSessionRestoreResult.temporarilyUnavailable;
      }
      ++_persistenceGeneration;
      try {
        await _mutateTokenStore(() => _tokenStore.deleteAccessToken());
      } catch (_) {
        return AuthSessionRestoreResult.temporarilyUnavailable;
      }
      return AuthSessionRestoreResult.rejected;
    }
  }

  Future<void> clearPersisted() async {
    ++_persistenceGeneration;
    _clearMemory();
    await _mutateTokenStore(() => _tokenStore.deleteAccessToken());
  }

  Future<bool> clearAfterRemoteInvalidation() async {
    ++_persistenceGeneration;
    _clearMemory();
    try {
      await _mutateTokenStore(() => _tokenStore.deleteAccessToken());
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
    ++_persistenceGeneration;
    _clearMemory();
    unawaited(_mutateTokenStore(() => _tokenStore.deleteAccessToken())
        .catchError((Object _) {}));
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