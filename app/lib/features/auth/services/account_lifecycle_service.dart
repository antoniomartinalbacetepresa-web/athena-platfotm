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
    required this._authService,
    required this._session,
  });

  final AthenaAuthService _authService;
  final AuthSession _session;

  Future<bool> _clearInvalidatedCredential(String invalidatedToken) async {
    // The remote request may complete after the user has already established a
    // different authenticated session. Never let an old lifecycle operation
    // revoke or delete the replacement authority. The invalidated token is
    // already non-authoritative server-side; only clear local state when it is
    // still the credential that authorized this operation.
    if (!_session.isAuthenticated || _session.accessToken != invalidatedToken) {
      return false;
    }
    return _session.clearAfterRemoteInvalidation();
  }

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

    final localCredentialDeleted = await _clearInvalidatedCredential(token);
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

    final localCredentialDeleted = await _clearInvalidatedCredential(token);
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

    final localCredentialDeleted = await _clearInvalidatedCredential(token);
    return AccountClosureResult(
      localCredentialDeleted: localCredentialDeleted,
    );
  }
}