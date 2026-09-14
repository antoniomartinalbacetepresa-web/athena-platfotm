import 'athena_auth_account_closure.dart';
import 'athena_auth_service.dart';
import 'auth_session.dart';

class AccountLifecycleService {
  AccountLifecycleService({
    required AthenaAuthService authService,
    required AuthSession session,
  })  : _authService = authService,
        _session = session;

  final AthenaAuthService _authService;
  final AuthSession _session;

  Future<void> closeCurrentAccount({required String currentPassword}) async {
    final token = _session.accessToken;
    if (token == null || !_session.isAuthenticated) {
      throw StateError('No existe una sesión autenticada para cerrar.');
    }
    await _authService.closeAccount(
      token: token,
      currentPassword: currentPassword,
    );
    try {
      await _session.clearPersisted();
    } catch (_) {
      _session.clear();
      rethrow;
    }
  }
}
