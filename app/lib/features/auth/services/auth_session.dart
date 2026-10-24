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
  int _persistAttemptVersion = 0;
  Future<void>? _pendingTokenMutation;
  bool _storageDeletionUnconfirmed = false;

  // Serialize only overlapping secure-storage writes/deletes. An uncontended
  // operation starts immediately, preserving widget-test and UI scheduling.
  Future<void> _mutateStoredToken(Future<void> Function() action) {
    final previous = _pendingTokenMutation;
    final operation =
        previous == null ? action() : previous.then((_) => action());
    final settled = operation.then<void>(
      (_) {},
      onError: (Object _, StackTrace __) {},
    );
    _pendingTokenMutation = settled;
    unawaited(settled.then((_) {
      if (identical(_pendingTokenMutation, settled)) {
        _pendingTokenMutation = null;
      }
    }));
    return operation;
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
    final authorityVersion = _authorityVersion;
    final attemptVersion = ++_persistAttemptVersion;
    await _mutateStoredToken(() => _tokenStore.writeAccessToken(token));
    if (_authorityVersion != authorityVersion ||
        _persistAttemptVersion != attemptVersion) {
      throw StateError('La autoridad cambió durante el inicio de sesión.');
    }
    _storageDeletionUnconfirmed = false;
    establish(accessToken: token, account: account);
  }

  Future<AuthSessionRestoreResult> restore({
    required Future<AuthAccount> Function(String token) validateToken,
    required bool Function(Object error) shouldDiscardToken,
  }) async {
    if (isAuthenticated) return AuthSessionRestoreResult.restored;
    final pending = _pendingTokenMutation;
    if (pending != null) await pending;
    if (_storageDeletionUnconfirmed) {
      return AuthSessionRestoreResult.temporarilyUnavailable;
    }
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
      _storageDeletionUnconfirmed = true;
      try {
        await _mutateStoredToken(() => _tokenStore.deleteAccessToken());
        _storageDeletionUnconfirmed = false;
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
      _storageDeletionUnconfirmed = true;
      try {
        await _mutateStoredToken(() => _tokenStore.deleteAccessToken());
        _storageDeletionUnconfirmed = false;
      } catch (_) {
        return AuthSessionRestoreResult.temporarilyUnavailable;
      }
      return AuthSessionRestoreResult.rejected;
    }
  }

  Future<void> clearPersisted() async {
    _clearMemory();
    _storageDeletionUnconfirmed = true;
    await _mutateStoredToken(() => _tokenStore.deleteAccessToken());
    _storageDeletionUnconfirmed = false;
  }

  Future<bool> clearAfterRemoteInvalidation() async {
    _clearMemory();
    _storageDeletionUnconfirmed = true;
    try {
      await _mutateStoredToken(() => _tokenStore.deleteAccessToken());
      _storageDeletionUnconfirmed = false;
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
    _storageDeletionUnconfirmed = true;
    unawaited(
      _mutateStoredToken(() => _tokenStore.deleteAccessToken()).then(
        (_) => _storageDeletionUnconfirmed = false,
        onError: (Object _) {},
      ),
    );
  }

  void _clearMemory() {
    final changed = _accessToken != null || _account != null;
    _accessToken = null;
    _account = null;
    // A clear is an authority transition even if memory was already empty.
    // Otherwise a pending restore can resurrect a session after logout.
    _authorityVersion += 1;
    _persistAttemptVersion += 1;
    if (changed) {
      notifyListeners();
    }
  }
}