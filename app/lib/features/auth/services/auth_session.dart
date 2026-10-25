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
  // A deletion may finish while a newer login write is still in flight.
  // Track completions so that read-back cannot accept a pre-delete value.
  int _completedDeletionEpoch = 0;
  int _pendingDeletions = 0;
  // A secure write can expose a token before its Future confirms durability.
  // Restoration must not authenticate that in-flight credential.
  int _pendingWrites = 0;

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
    _pendingWrites += 1;
    try {
      await _tokenStore.writeAccessToken(token);
      if (_authorityVersion != writeAuthorityVersion) {
        await _reconcilePersistedAuthority();
        throw StateError('La sesión cambió durante el inicio de sesión.');
      }

      // A previously scheduled logout may delete this token *after* the
      // secure write takes effect but *before* its Future completes. Verify
      // durable state before exposing authenticated authority. If a deletion
      // completes during the read, retry rather than trusting a stale read.
      for (var attempt = 0; attempt < 3; attempt++) {
        final deletionEpoch = _completedDeletionEpoch;
        final stored = await _tokenStore.readAccessToken();
        if (_authorityVersion != writeAuthorityVersion) {
          await _reconcilePersistedAuthority();
          throw StateError('La sesión cambió durante el inicio de sesión.');
        }
        if (deletionEpoch != _completedDeletionEpoch) {
          continue;
        }
        if (stored == token) {
          establish(accessToken: token, account: account);
          return;
        }
        await _tokenStore.writeAccessToken(token);
      }
      throw StateError('No se pudo confirmar la credencial persistida.');
    } catch (_) {
      // A failed verification must not expose a session whose durable token
      // may have been removed. Never revoke a newer authenticated authority.
      if (_authorityVersion == writeAuthorityVersion) {
        _clearMemory();
      }
      rethrow;
    } finally {
      _pendingWrites -= 1;
    }
  }

  Future<AuthSessionRestoreResult> restore({
    required Future<AuthAccount> Function(String token) validateToken,
    required bool Function(Object error) shouldDiscardToken,
  }) async {
    if (isAuthenticated) return AuthSessionRestoreResult.restored;
    // A logout may have revoked memory before its secure deletion finishes.
    // Never restore the still-visible token while that deletion is pending.
    if (_pendingDeletions > 0 || _pendingWrites > 0) {
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
    if (_pendingWrites > 0) {
      return AuthSessionRestoreResult.temporarilyUnavailable;
    }
    if (storedToken == null) {
      _clearMemory();
      return AuthSessionRestoreResult.noStoredToken;
    }

    final token = storedToken.trim();
    if (token.isEmpty) {
      _clearMemory();
      // A newer login may finish while this stale restore deletes its token.
      // Reconcile with the current authority instead of erasing that login.
      final deletionAuthorityVersion = _authorityVersion;
      try {
        await _deletePersistedForAuthority(deletionAuthorityVersion);
      } catch (_) {
        return AuthSessionRestoreResult.temporarilyUnavailable;
      }
      return _authorityVersion != deletionAuthorityVersion && isAuthenticated
          ? AuthSessionRestoreResult.restored
          : AuthSessionRestoreResult.rejected;
    }

    try {
      final account = await validateToken(token);
      if (_authorityVersion != restoreAuthorityVersion) {
        return isAuthenticated
            ? AuthSessionRestoreResult.restored
            : AuthSessionRestoreResult.temporarilyUnavailable;
      }
      // Validation may take longer than a secure-storage mutation. Confirm
      // that the same credential still exists before restoring authority.
      final deletionEpoch = _completedDeletionEpoch;
      final String? confirmedToken;
      try {
        confirmedToken = await _tokenStore.readAccessToken();
      } catch (_) {
        if (_authorityVersion == restoreAuthorityVersion) {
          _clearMemory();
        }
        return AuthSessionRestoreResult.temporarilyUnavailable;
      }
      if (_authorityVersion != restoreAuthorityVersion) {
        return isAuthenticated
            ? AuthSessionRestoreResult.restored
            : AuthSessionRestoreResult.temporarilyUnavailable;
      }
      if (_pendingDeletions > 0 ||
          _pendingWrites > 0 ||
          deletionEpoch != _completedDeletionEpoch ||
          confirmedToken?.trim() != token) {
        _clearMemory();
        return AuthSessionRestoreResult.temporarilyUnavailable;
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
      // A newer login may finish while this stale restore deletes its token.
      // Reconcile with the current authority instead of erasing that login.
      final deletionAuthorityVersion = _authorityVersion;
      try {
        await _deletePersistedForAuthority(deletionAuthorityVersion);
      } catch (_) {
        return AuthSessionRestoreResult.temporarilyUnavailable;
      }
      return _authorityVersion != deletionAuthorityVersion && isAuthenticated
          ? AuthSessionRestoreResult.restored
          : AuthSessionRestoreResult.rejected;
    }
  }

  Future<void> clearPersisted() async {
    _clearMemory();
    final clearedVersion = _authorityVersion;
    await _deletePersistedForAuthority(clearedVersion);
  }

  Future<bool> clearAfterRemoteInvalidation() async {
    _clearMemory();
    final clearedVersion = _authorityVersion;
    try {
      await _deletePersistedForAuthority(clearedVersion);
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
    final clearedVersion = _authorityVersion;
    unawaited(
      _deletePersistedForAuthority(clearedVersion).catchError((Object _) {}),
    );
  }

  // A logout deletion may complete after another account has logged in.
  // Repair only when that deletion outlives its original authority.
  Future<void> _deletePersistedForAuthority(int clearedVersion) async {
    _pendingDeletions += 1;
    try {
      await _tokenStore.deleteAccessToken();
      _completedDeletionEpoch += 1;
      if (_authorityVersion != clearedVersion) {
        await _reconcilePersistedAuthority();
      }
    } finally {
      _pendingDeletions -= 1;
    }
  }

  // Never serialize all secure-storage operations in a global queue: widget
  // tests and Portfolio invalidation must remain free to make progress.
  Future<void> _reconcilePersistedAuthority() async {
    while (true) {
      final repairVersion = _authorityVersion;
      try {
        if (isAuthenticated) {
          await _tokenStore.writeAccessToken(_accessToken!);
        } else {
          await _tokenStore.deleteAccessToken();
          _completedDeletionEpoch += 1;
        }
      } catch (_) {
        // Do not revoke an account established after this repair started.
        if (_authorityVersion == repairVersion) {
          _clearMemory();
        }
        rethrow;
      }
      if (_authorityVersion == repairVersion) {
        return;
      }
    }
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