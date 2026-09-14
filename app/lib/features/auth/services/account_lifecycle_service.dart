import 'athena_auth_account_closure.dart';
import 'athena_auth_service.dart';
import 'auth_session.dart';

class AccountClosureResult {
  const AccountClosureResult({required this.localCredentialDeleted});

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
