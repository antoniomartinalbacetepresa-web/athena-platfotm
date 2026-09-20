import 'dart:async';

import 'package:flutter/material.dart';

import '../../../../core/routing/app_routes.dart';
import '../../../../core/theme/athena_colors.dart';
import '../../../auth/models/auth_account.dart';
import '../../../auth/services/account_lifecycle_service.dart';
import '../../../auth/services/athena_auth_service.dart';
import '../../../auth/services/auth_session.dart';
import '../../models/user_preferences.dart';
import '../../services/user_preferences_service.dart';

class ProfilePage extends StatefulWidget {
  const ProfilePage({
    super.key,
    this.authService,
    this.accountLifecycleService,
  });

  final AthenaAuthService? authService;
  final AccountLifecycleService? accountLifecycleService;

  @override
  State<ProfilePage> createState() => _ProfilePageState();
}

class _ProfilePageState extends State<ProfilePage> {
  late final AthenaAuthService _authService;
  late final bool _ownsAuthService;
  late final AccountLifecycleService _accountLifecycleService;
  final UserPreferencesService _preferencesService = UserPreferencesService();

  bool _checking = false;
  bool _preferencesBusy = false;
  String? _error;
  String? _sessionValidationError;
  String? _preferencesError;
  UserPreferences? _preferences;

  @override
  void initState() {
    super.initState();
    _ownsAuthService = widget.authService == null;
    _authService = widget.authService ?? AthenaAuthService();
    _accountLifecycleService = widget.accountLifecycleService ??
        AccountLifecycleService(
          authService: _authService,
          session: AuthSession.instance,
        );
    _refreshAuthenticatedAccount();
  }

  @override
  void dispose() {
    if (_ownsAuthService) _authService.dispose();
    _preferencesService.dispose();
    super.dispose();
  }

  Future<void> _refreshAuthenticatedAccount() async {
    final token = AuthSession.instance.accessToken;
    if (token == null) return;
    setState(() {
      _checking = true;
      _error = null;
      _sessionValidationError = null;
    });
    try {
      final account = await _authService.getMe(token);
      AuthSession.instance.establish(accessToken: token, account: account);
      await _loadPreferences();
    } on AuthSessionRejectedException {
      // clearAfterRemoteInvalidation revokes in-memory authority before its
      // first await. Do not keep the protected UI blocked on secure-storage I/O.
      unawaited(AuthSession.instance.clearAfterRemoteInvalidation());
      _preferences = null;
      _preferencesError = null;
      _sessionValidationError = null;
      _error = 'La sesión ha caducado o ya no es válida.';
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _sessionValidationError =
            'No se pudo revalidar la sesión por un problema temporal. La sesión local se conserva sin asumir que ha sido revocada.';
      });
    } finally {
      if (mounted) setState(() => _checking = false);
    }
  }

  Future<void> _loadPreferences() async {
    if (!AuthSession.instance.isAuthenticated) return;
    setState(() {
      _preferencesBusy = true;
      _preferencesError = null;
    });
    try {
      final preferences = await _preferencesService.load();
      if (!mounted) return;
      setState(() => _preferences = preferences);
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _preferencesError =
            'No se pudieron cargar las preferencias protegidas. No se han sustituido por datos locales.';
      });
    } finally {
      if (mounted) setState(() => _preferencesBusy = false);
    }
  }

  Future<void> _savePreferences(UserPreferences preferences) async {
    setState(() {
      _preferencesBusy = true;
      _preferencesError = null;
    });
    try {
      final stored = await _preferencesService.save(preferences);
      if (!mounted) return;
      setState(() => _preferences = stored);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Preferencias protegidas guardadas.')),
      );
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _preferencesError =
            'No se pudieron guardar las preferencias. No se conservará una copia local insegura.';
      });
    } finally {
      if (mounted) setState(() => _preferencesBusy = false);
    }
  }

  Future<void> _deletePreferences() async {
    setState(() {
      _preferencesBusy = true;
      _preferencesError = null;
    });
    try {
      await _preferencesService.delete();
      if (!mounted) return;
      setState(() => _preferences = null);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Preferencias protegidas eliminadas.')),
      );
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _preferencesError = 'No se pudieron eliminar las preferencias protegidas.';
      });
    } finally {
      if (mounted) setState(() => _preferencesBusy = false);
    }
  }

  Future<void> _logout() async {
    try {
      await _accountLifecycleService.logoutCurrentSession();
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _sessionValidationError =
            'No se pudo confirmar el cierre de sesión en el servidor. La sesión se conserva hasta poder verificar la revocación.';
      });
      return;
    }
    if (!mounted) return;
    Navigator.pushNamedAndRemoveUntil(
      context,
      AppRoutes.welcome,
      (route) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    final account = AuthSession.instance.account;
    return Scaffold(
      backgroundColor: AthenaColors.background,
      appBar: AppBar(
        backgroundColor: AthenaColors.background,
        foregroundColor: AthenaColors.text,
        elevation: 0,
        title: const Text('PERFIL'),
      ),
      body: SafeArea(
        child: _checking
            ? const Center(child: CircularProgressIndicator())
            : account == null
                ? _GuestProfileState(error: _error)
                : _AuthenticatedProfile(
                    account: account,
                    sessionValidationError: _sessionValidationError,
                    preferences: _preferences,
                    preferencesBusy: _preferencesBusy,
                    preferencesError: _preferencesError,
                    onRefresh: _refreshAuthenticatedAccount,
                    onReloadPreferences: _loadPreferences,
                    onSavePreferences: _savePreferences,
                    onDeletePreferences: _deletePreferences,
                    onLogout: _logout,
                  ),
      ),
    );
  }
}

class _GuestProfileState extends StatelessWidget {
  const _GuestProfileState({this.error});

  final String? error;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: Container(
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
              color: AthenaColors.card,
              borderRadius: BorderRadius.circular(18),
              border: Border.all(color: AthenaColors.border),
            ),
            child: Column(
              children: [
                const Icon(
                  Icons.lock_person_outlined,
                  color: AthenaColors.primary,
                  size: 44,
                ),
                const SizedBox(height: 14),
                const Text(
                  'Perfil protegido',
                  style: TextStyle(
                    color: AthenaColors.text,
                    fontSize: 22,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 10),
                const Text(
                  'Inicia sesión para acceder a tus datos y preferencias protegidas.',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: AthenaColors.textSecondary),
                ),
                if (error != null) ...[
                  const SizedBox(height: 12),
                  Text(
                    error!,
                    textAlign: TextAlign.center,
                    style: const TextStyle(color: AthenaColors.warning),
                  ),
                ],
                const SizedBox(height: 18),
                FilledButton(
                  onPressed: () => Navigator.pushNamedAndRemoveUntil(
                    context,
                    AppRoutes.login,
                    (route) => false,
                  ),
                  child: const Text('INICIAR SESIÓN'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _AuthenticatedProfile extends StatelessWidget {
  const _AuthenticatedProfile({
    required this.account,
    required this.sessionValidationError,
    required this.preferences,
    required this.preferencesBusy,
    required this.preferencesError,
    required this.onRefresh,
    required this.onReloadPreferences,
    required this.onSavePreferences,
    required this.onDeletePreferences,
    required this.onLogout,
  });

  final AuthAccount account;
  final String? sessionValidationError;
  final UserPreferences? preferences;
  final bool preferencesBusy;
  final String? preferencesError;
  final Future<void> Function() onRefresh;
  final Future<void> Function() onReloadPreferences;
  final Future<void> Function(UserPreferences) onSavePreferences;
  final Future<void> Function() onDeletePreferences;
  final Future<void> Function() onLogout;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        Text(
          'Identidad autenticada',
          style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                color: AthenaColors.text,
                fontWeight: FontWeight.w700,
              ),
        ),
        const SizedBox(height: 16),
        Text(account.displayName ?? account.email,
            style: const TextStyle(color: AthenaColors.text)),
        Text(account.email,
            style: const TextStyle(color: AthenaColors.textSecondary)),
        if (sessionValidationError != null) ...[
          const SizedBox(height: 12),
          Text(sessionValidationError!,
              style: const TextStyle(color: AthenaColors.warning)),
        ],
        const SizedBox(height: 16),
        OutlinedButton(
          onPressed: onRefresh,
          child: const Text('REVALIDAR SESIÓN'),
        ),
        const SizedBox(height: 24),
        _PreferencesPanel(
          preferences: preferences,
          busy: preferencesBusy,
          error: preferencesError,
          onReload: onReloadPreferences,
          onSave: onSavePreferences,
          onDelete: onDeletePreferences,
        ),
        const SizedBox(height: 24),
        OutlinedButton(
          onPressed: onLogout,
          child: const Text('CERRAR SESIÓN'),
        ),
      ],
    );
  }
}

class _PreferencesPanel extends StatelessWidget {
  const _PreferencesPanel({
    required this.preferences,
    required this.busy,
    required this.error,
    required this.onReload,
    required this.onSave,
    required this.onDelete,
  });

  final UserPreferences? preferences;
  final bool busy;
  final String? error;
  final Future<void> Function() onReload;
  final Future<void> Function(UserPreferences) onSave;
  final Future<void> Function() onDelete;

  @override
  Widget build(BuildContext context) {
    return const SizedBox.shrink();
  }
}
