import 'athena_auth_account_closure.dart';
import 'athena_auth_service.dart';
import 'auth_session.dart';

class AccountClosureResult {
  const AccountClosureResult({required this.localCredentialDeleted});

  final bool localCredentialDeleted;
}

class SessionLogoutResult {
  const SessionLogoutResult({required this.localCredentialDeleted});

  final bool localCredentialDeleted;
}

class PasswordChangeResult {
  const PasswordChangeResult({required this.localCredentialDeleted});

  final bool localCredentialDeleted;
}

class AccountLifecycleService {
  AccountLifecycleService({
    required AthenaAuthService authService,
    required AuthSession session,
  })  : _authService = authService,
        _session = session;

  final AthenaAuthService _authService;
  final AuthSession _session;

  Future<PasswordChangeResult> changeCurrentPassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    final token = _session.accessToken;
    if (token == null || !_session.isAuthenticated) {
      throw StateError('No existe una sesión autenticada para cambiar la contraseña.');
    }

    await _authService.changePassword(
      token: token,
      currentPassword: currentPassword,
      newPassword: newPassword,
    );

    // Password rotation invalidates every server-side session version, including
    // the credential that authorized this request. Never leave that now-stale
    // credential authoritative in memory if secure-storage deletion fails.
    final localCredentialDeleted = await _session.clearAfterRemoteInvalidation();
    return PasswordChangeResult(
      localCredentialDeleted: localCredentialDeleted,
    );
  }

  Future<SessionLogoutResult> logoutCurrentSession() async {
    return _logout(allSessions: false);
  }

  Future<SessionLogoutResult> logoutAllSessions() async {
    return _logout(allSessions: true);
  }

  Future<SessionLogoutResult> _logout({required bool allSessions}) async {
    final token = _session.accessToken;
    if (token == null || !_session.isAuthenticated) {
      throw StateError('No existe una sesión autenticada para cerrar.');
    }

    if (allSessions) {
      await _authService.logoutAll(token);
    } else {
      await _authService.logout(token);
    }

    // A successful remote revocation is authoritative. Clear in-memory auth
    // before attempting secure-storage cleanup so a local storage failure can
    // never leave the client authenticated with a server-revoked credential.
    final localCredentialDeleted = await _session.clearAfterRemoteInvalidation();
    return SessionLogoutResult(
      localCredentialDeleted: localCredentialDeleted,
    );
  }

  Future<AccountClosureResult> closeCurrentAccount({
    required String currentPassword,
  }) async {
    final token = _session.accessToken;
    if (token == null || !_session.isAuthenticated) {
      throw StateError('No existe una sesión autenticada para cerrar.');
    }
    await _authService.closeAccount(
      token: token,
      currentPassword: currentPassword,
    );

    // A 204 means the backend already completed an irreversible account
    // closure. Local secure-storage cleanup must never make the UI report that
    // the remote closure failed. Memory is cleared unconditionally; callers may
    // still observe whether the stale durable credential was deleted locally.
    final localCredentialDeleted = await _session.clearAfterRemoteInvalidation();
    return AccountClosureResult(
      localCredentialDeleted: localCredentialDeleted,
    );
  }
}