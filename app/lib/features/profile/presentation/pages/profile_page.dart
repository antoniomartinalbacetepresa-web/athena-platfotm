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
  const ProfilePage({super.key, this.authService});

  final AthenaAuthService? authService;

  @override
  State<ProfilePage> createState() => _ProfilePageState();
}

class _ProfilePageState extends State<ProfilePage> {
  late final AthenaAuthService _authService;
  late final bool _ownsAuthService;
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
    final lifecycle = AccountLifecycleService(
      authService: _authService,
      session: AuthSession.instance,
    );
    try {
      await lifecycle.logoutCurrentSession();
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
                const SizedBox(height: 8),
                Text(
                  error ??
                      'Estás usando ATHENA como invitado. Inicia sesión para acceder a tus preferencias protegidas.',
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    color: AthenaColors.textSecondary,
                    height: 1.4,
                  ),
                ),
                const SizedBox(height: 20),
                ElevatedButton(
                  onPressed: () => Navigator.pushNamed(context, AppRoutes.login),
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
        if (sessionValidationError != null) ...[
          Container(
            key: const Key('profile-session-validation-error'),
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: Colors.orange.withValues(alpha: 0.08),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: Colors.orangeAccent),
            ),
            child: Text(
              sessionValidationError!,
              style: const TextStyle(
                color: AthenaColors.textSecondary,
                height: 1.35,
              ),
            ),
          ),
          const SizedBox(height: 16),
        ],
        _IdentityCard(account: account),
        const SizedBox(height: 16),
        ProfilePreferencesForm(
          preferences: preferences,
          busy: preferencesBusy,
          error: preferencesError,
          onReload: onReloadPreferences,
          onSave: onSavePreferences,
          onDelete: preferences == null ? null : onDeletePreferences,
        ),
        const SizedBox(height: 12),
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: AthenaColors.card,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AthenaColors.border),
          ),
          child: const ListTile(
            contentPadding: EdgeInsets.zero,
            leading: Icon(Icons.language_rounded),
            title: Text('Idioma'),
            subtitle: Text('Español es el idioma activo de la versión inicial.'),
            trailing: Text('Español'),
          ),
        ),
        const SizedBox(height: 20),
        OutlinedButton.icon(
          onPressed: preferencesBusy ? null : onRefresh,
          icon: const Icon(Icons.refresh_rounded),
          label: const Text('VALIDAR SESIÓN'),
        ),
        const SizedBox(height: 10),
        TextButton.icon(
          onPressed: preferencesBusy ? null : onLogout,
          icon: const Icon(Icons.logout_rounded),
          label: const Text('CERRAR SESIÓN'),
        ),
      ],
    );
  }
}

class ProfilePreferencesForm extends StatefulWidget {
  const ProfilePreferencesForm({
    super.key,
    required this.preferences,
    required this.busy,
    required this.onReload,
    required this.onSave,
    this.onDelete,
    this.error,
  });

  final UserPreferences? preferences;
  final bool busy;
  final String? error;
  final Future<void> Function() onReload;
  final Future<void> Function(UserPreferences) onSave;
  final Future<void> Function()? onDelete;

  @override
  State<ProfilePreferencesForm> createState() => _ProfilePreferencesFormState();
}

class _ProfilePreferencesFormState extends State<ProfilePreferencesForm> {
  final _formKey = GlobalKey<FormState>();
  final TextEditingController _horizonController = TextEditingController();
  final TextEditingController _currencyController = TextEditingController();
  final TextEditingController _drawdownController = TextEditingController();
  final TextEditingController _capitalController = TextEditingController();
  late String _riskTolerance;
  late String _objective;
  late String? _experienceLevel;
  late String? _liquidityNeed;

  @override
  void initState() {
    super.initState();
    _sync(widget.preferences);
  }

  @override
  void didUpdateWidget(covariant ProfilePreferencesForm oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.preferences != widget.preferences) {
      _sync(widget.preferences);
    }
  }

  void _sync(UserPreferences? preferences) {
    final value = preferences ?? UserPreferences.defaults();
    _riskTolerance = value.riskTolerance;
    _objective = value.objective;
    _experienceLevel = value.experienceLevel;
    _liquidityNeed = value.liquidityNeed;
    _horizonController.text = value.investmentHorizonYears.toString();
    _currencyController.text = value.baseCurrency;
    _drawdownController.text = value.maxDrawdownTolerancePct?.toString() ?? '';
    _capitalController.text = value.availableCapital?.toString() ?? '';
  }

  @override
  void dispose() {
    _horizonController.dispose();
    _currencyController.dispose();
    _drawdownController.dispose();
    _capitalController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Form(
      key: _formKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text(
            'Preferencias protegidas',
            style: TextStyle(
              color: AthenaColors.text,
              fontSize: 18,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            'Se sincronizan únicamente mediante la API autenticada y se almacenan cifradas en el backend.',
            style: TextStyle(color: AthenaColors.textSecondary, height: 1.35),
          ),
          const SizedBox(height: 6),
          const Text(
            'Estas preferencias adaptan la presentación; no autorizan operaciones ni modifican automáticamente el scoring o el weighting canónico.',
            key: Key('personalization-safety-note'),
            style: TextStyle(color: AthenaColors.textSecondary, height: 1.35),
          ),
          const SizedBox(height: 14),
          if (widget.error != null) ...[
            Text(
              widget.error!,
              style: const TextStyle(color: Colors.orangeAccent),
            ),
            const SizedBox(height: 10),
          ],
          if (widget.busy) ...[
            const LinearProgressIndicator(),
            const SizedBox(height: 12),
          ],
          DropdownButtonFormField<String>(
            initialValue: _riskTolerance,
            decoration: const InputDecoration(labelText: 'Tolerancia al riesgo'),
            items: const [
              DropdownMenuItem(value: 'conservative', child: Text('Conservadora')),
              DropdownMenuItem(value: 'balanced', child: Text('Equilibrada')),
              DropdownMenuItem(value: 'growth', child: Text('Crecimiento')),
            ],
            onChanged: widget.busy
                ? null
                : (value) => setState(() => _riskTolerance = value!),
          ),
          const SizedBox(height: 12),
          TextFormField(
            controller: _horizonController,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(labelText: 'Horizonte (años)'),
            validator: (value) {
              final parsed = int.tryParse(value ?? '');
              if (parsed == null || parsed < 1 || parsed > 60) {
                return 'Introduce un horizonte entre 1 y 60 años.';
              }
              return null;
            },
          ),
          const SizedBox(height: 12),
          TextFormField(
            controller: _currencyController,
            textCapitalization: TextCapitalization.characters,
            decoration: const InputDecoration(labelText: 'Divisa base'),
            validator: (value) {
              final normalized = (value ?? '').trim().toUpperCase();
              if (!RegExp(r'^[A-Z]{3}$').hasMatch(normalized)) {
                return 'Usa un código ISO de tres letras, por ejemplo EUR.';
              }
              return null;
            },
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _objective,
            decoration: const InputDecoration(labelText: 'Objetivo'),
            items: const [
              DropdownMenuItem(
                value: 'capital_preservation',
                child: Text('Preservar capital'),
              ),
              DropdownMenuItem(
                value: 'balanced_growth',
                child: Text('Crecimiento equilibrado'),
              ),
              DropdownMenuItem(
                value: 'long_term_growth',
                child: Text('Crecimiento a largo plazo'),
              ),
            ],
            onChanged: widget.busy
                ? null
                : (value) => setState(() => _objective = value!),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String?>(
            key: const Key('experience-level-field'),
            initialValue: _experienceLevel,
            decoration: const InputDecoration(labelText: 'Experiencia'),
            items: const [
              DropdownMenuItem(value: null, child: Text('Sin especificar')),
              DropdownMenuItem(value: 'beginner', child: Text('Principiante')),
              DropdownMenuItem(value: 'intermediate', child: Text('Intermedia')),
              DropdownMenuItem(value: 'advanced', child: Text('Avanzada')),
            ],
            onChanged: widget.busy
                ? null
                : (value) => setState(() => _experienceLevel = value),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String?>(
            key: const Key('liquidity-need-field'),
            initialValue: _liquidityNeed,
            decoration: const InputDecoration(labelText: 'Necesidad de liquidez'),
            items: const [
              DropdownMenuItem(value: null, child: Text('Sin especificar')),
              DropdownMenuItem(value: 'low', child: Text('Baja')),
              DropdownMenuItem(value: 'medium', child: Text('Media')),
              DropdownMenuItem(value: 'high', child: Text('Alta')),
            ],
            onChanged: widget.busy
                ? null
                : (value) => setState(() => _liquidityNeed = value),
          ),
          const SizedBox(height: 12),
          TextFormField(
            key: const Key('max-drawdown-field'),
            controller: _drawdownController,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(
              labelText: 'Drawdown máximo tolerado (%)',
            ),
            validator: (value) {
              final raw = (value ?? '').trim();
              if (raw.isEmpty) return null;
              final parsed = int.tryParse(raw);
              if (parsed == null || parsed < 5 || parsed > 60) {
                return 'Introduce un drawdown entre 5% y 60%, o déjalo vacío.';
              }
              return null;
            },
          ),
          const SizedBox(height: 12),
          TextFormField(
            key: const Key('available-capital-field'),
            controller: _capitalController,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(labelText: 'Capital disponible'),
            validator: (value) {
              final raw = (value ?? '').trim().replaceAll(',', '.');
              if (raw.isEmpty) return null;
              final parsed = double.tryParse(raw);
              if (parsed == null || parsed < 0 || parsed > 1000000000000) {
                return 'Introduce un capital entre 0 y 1.000.000.000.000, o déjalo vacío.';
              }
              return null;
            },
          ),
          const SizedBox(height: 18),
          ElevatedButton(
            onPressed: widget.busy
                ? null
                : () async {
                    if (!(_formKey.currentState?.validate() ?? false)) return;
                    final drawdownRaw = _drawdownController.text.trim();
                    final capitalRaw =
                        _capitalController.text.trim().replaceAll(',', '.');
                    await widget.onSave(
                      UserPreferences(
                        riskTolerance: _riskTolerance,
                        investmentHorizonYears:
                            int.parse(_horizonController.text.trim()),
                        baseCurrency:
                            _currencyController.text.trim().toUpperCase(),
                        objective: _objective,
                        experienceLevel: _experienceLevel,
                        liquidityNeed: _liquidityNeed,
                        maxDrawdownTolerancePct:
                            drawdownRaw.isEmpty ? null : int.parse(drawdownRaw),
                        availableCapital:
                            capitalRaw.isEmpty ? null : double.parse(capitalRaw),
                      ),
                    );
                  },
            child: const Text('GUARDAR'),
          ),
          const SizedBox(height: 8),
          OutlinedButton(
            onPressed: widget.busy ? null : widget.onReload,
            child: const Text('RECARGAR'),
          ),
          if (widget.onDelete != null) ...[
            const SizedBox(height: 8),
            TextButton(
              onPressed: widget.busy ? null : widget.onDelete,
              child: const Text('ELIMINAR PREFERENCIAS'),
            ),
          ],
          if (widget.preferences != null) ...[
            const SizedBox(height: 12),
            const Text(
              'Preferencias cargadas desde almacenamiento cifrado.',
              style: TextStyle(
                color: AthenaColors.textSecondary,
                fontSize: 12,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _IdentityCard extends StatelessWidget {
  const _IdentityCard({required this.account});

  final AuthAccount account;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AthenaColors.card,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AthenaColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Identidad autenticada',
            style: TextStyle(
              color: AthenaColors.text,
              fontSize: 18,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 10),
          Text(
            account.displayName ?? 'Sin nombre público',
            style: const TextStyle(color: AthenaColors.text),
          ),
          const SizedBox(height: 4),
          Text(
            account.email,
            style: const TextStyle(color: AthenaColors.textSecondary),
          ),
        ],
      ),
    );
  }
}
