import 'package:flutter/material.dart';

import '../../../../core/routing/app_routes.dart';
import '../../../../core/theme/athena_colors.dart';
import '../../../auth/models/auth_account.dart';
import '../../../auth/services/athena_auth_service.dart';
import '../../../auth/services/auth_session.dart';
import '../../models/user_preferences.dart';
import '../../services/user_preferences_service.dart';

class ProfilePage extends StatefulWidget {
  const ProfilePage({super.key});

  @override
  State<ProfilePage> createState() => _ProfilePageState();
}

class _ProfilePageState extends State<ProfilePage> {
  final AthenaAuthService _authService = AthenaAuthService();
  final UserPreferencesService _preferencesService = UserPreferencesService();

  bool _checking = false;
  bool _preferencesBusy = false;
  String? _error;
  String? _preferencesError;
  UserPreferences? _preferences;

  @override
  void initState() {
    super.initState();
    _refreshAuthenticatedAccount();
  }

  @override
  void dispose() {
    _authService.dispose();
    _preferencesService.dispose();
    super.dispose();
  }

  Future<void> _refreshAuthenticatedAccount() async {
    final token = AuthSession.instance.accessToken;
    if (token == null) return;
    setState(() {
      _checking = true;
      _error = null;
    });
    try {
      final account = await _authService.getMe(token);
      AuthSession.instance.establish(accessToken: token, account: account);
      await _loadPreferences();
    } catch (_) {
      AuthSession.instance.clear();
      _preferences = null;
      _preferencesError = null;
      _error = 'La sesión ha caducado o ya no es válida.';
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
    final token = AuthSession.instance.accessToken;
    if (token != null) {
      try {
        await _authService.logout(token);
      } catch (_) {
        // Local session is still cleared. A failed remote revocation must not
        // trap the user inside an invalid client session.
      }
    }
    AuthSession.instance.clear();
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
        const _ProfileSection(
          icon: Icons.language_rounded,
          title: 'Idioma',
          description: 'Español es el idioma activo de la versión inicial.',
          status: 'Español',
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
  static const _unspecified = 'unspecified';

  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _horizonController;
  late final TextEditingController _currencyController;
  late final TextEditingController _availableCapitalController;
  late final TextEditingController _drawdownController;
  late String _riskTolerance;
  late String _objective;
  late String _experienceLevel;
  late String _liquidityNeed;

  @override
  void initState() {
    super.initState();
    _horizonController = TextEditingController();
    _currencyController = TextEditingController();
    _availableCapitalController = TextEditingController();
    _drawdownController = TextEditingController();
    _apply(widget.preferences);
  }

  @override
  void didUpdateWidget(covariant ProfilePreferencesForm oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.preferences != widget.preferences) {
      _apply(widget.preferences);
    }
  }

  void _apply(UserPreferences? value) {
    _riskTolerance = value?.riskTolerance ?? 'balanced';
    _objective = value?.objective ?? 'balanced_growth';
    _experienceLevel = value?.experienceLevel ?? _unspecified;
    _liquidityNeed = value?.liquidityNeed ?? _unspecified;
    _horizonController.text = (value?.investmentHorizonYears ?? 10).toString();
    _currencyController.text = value?.baseCurrency ?? 'EUR';
    _availableCapitalController.text = value?.availableCapital?.toString() ?? '';
    _drawdownController.text = value?.maxDrawdownTolerancePct?.toString() ?? '';
  }

  @override
  void dispose() {
    _horizonController.dispose();
    _currencyController.dispose();
    _availableCapitalController.dispose();
    _drawdownController.dispose();
    super.dispose();
  }

  String _normalizedCapitalText() =>
      _availableCapitalController.text.trim().replaceAll(',', '.');

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    final drawdownText = _drawdownController.text.trim();
    final capitalText = _normalizedCapitalText();
    final preferences = UserPreferences(
      riskTolerance: _riskTolerance,
      investmentHorizonYears: int.parse(_horizonController.text.trim()),
      baseCurrency: _currencyController.text.trim().toUpperCase(),
      objective: _objective,
      experienceLevel:
          _experienceLevel == _unspecified ? null : _experienceLevel,
      liquidityNeed: _liquidityNeed == _unspecified ? null : _liquidityNeed,
      maxDrawdownTolerancePct:
          drawdownText.isEmpty ? null : int.parse(drawdownText),
      availableCapital: capitalText.isEmpty ? null : double.parse(capitalText),
    );
    await widget.onSave(preferences);
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AthenaColors.card,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AthenaColors.border),
      ),
      child: Form(
        key: _formKey,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Row(
              children: [
                Icon(Icons.tune_rounded, color: AthenaColors.primary),
                SizedBox(width: 12),
                Expanded(
                  child: Text(
                    'Preferencias protegidas',
                    style: TextStyle(
                      color: AthenaColors.text,
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            const Text(
              'Se guardan cifradas en el backend asociado a tu cuenta. ATHENA no mantiene una copia local de estos campos.',
              style: TextStyle(color: AthenaColors.textSecondary, height: 1.35),
            ),
            const SizedBox(height: 6),
            const Text(
              'Estas preferencias aportan contexto. No activan recomendaciones, ponderaciones ni operaciones automáticas.',
              key: Key('personalization-safety-note'),
              style: TextStyle(
                color: AthenaColors.textSecondary,
                fontSize: 11,
                height: 1.35,
              ),
            ),
            if (widget.error != null) ...[
              const SizedBox(height: 10),
              Text(
                widget.error!,
                style: const TextStyle(color: Colors.redAccent, fontSize: 12),
              ),
            ],
            const SizedBox(height: 16),
            DropdownButtonFormField<String>(
              value: _riskTolerance,
              decoration: const InputDecoration(labelText: 'Tolerancia al riesgo'),
              items: const [
                DropdownMenuItem(value: 'conservative', child: Text('Conservadora')),
                DropdownMenuItem(value: 'balanced', child: Text('Equilibrada')),
                DropdownMenuItem(value: 'growth', child: Text('Crecimiento')),
                DropdownMenuItem(value: 'aggressive', child: Text('Agresiva')),
              ],
              onChanged: widget.busy
                  ? null
                  : (value) {
                      if (value != null) setState(() => _riskTolerance = value);
                    },
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              value: _objective,
              decoration: const InputDecoration(labelText: 'Objetivo'),
              items: const [
                DropdownMenuItem(
                  value: 'capital_preservation',
                  child: Text('Preservación de capital'),
                ),
                DropdownMenuItem(value: 'income', child: Text('Ingresos')),
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
                  : (value) {
                      if (value != null) setState(() => _objective = value);
                    },
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              key: const Key('experience-level-field'),
              value: _experienceLevel,
              decoration: const InputDecoration(labelText: 'Experiencia inversora'),
              items: const [
                DropdownMenuItem(value: _unspecified, child: Text('No indicada')),
                DropdownMenuItem(value: 'beginner', child: Text('Principiante')),
                DropdownMenuItem(value: 'intermediate', child: Text('Intermedia')),
                DropdownMenuItem(value: 'advanced', child: Text('Avanzada')),
              ],
              onChanged: widget.busy
                  ? null
                  : (value) {
                      if (value != null) setState(() => _experienceLevel = value);
                    },
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              key: const Key('liquidity-need-field'),
              value: _liquidityNeed,
              decoration: const InputDecoration(labelText: 'Necesidad de liquidez'),
              items: const [
                DropdownMenuItem(value: _unspecified, child: Text('No indicada')),
                DropdownMenuItem(value: 'low', child: Text('Baja')),
                DropdownMenuItem(value: 'medium', child: Text('Media')),
                DropdownMenuItem(value: 'high', child: Text('Alta')),
              ],
              onChanged: widget.busy
                  ? null
                  : (value) {
                      if (value != null) setState(() => _liquidityNeed = value);
                    },
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _horizonController,
              enabled: !widget.busy,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(labelText: 'Horizonte (años)'),
              validator: (value) {
                final years = int.tryParse(value?.trim() ?? '');
                if (years == null || years < 1 || years > 60) {
                  return 'Introduce un horizonte entre 1 y 60 años.';
                }
                return null;
              },
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _currencyController,
              enabled: !widget.busy,
              textCapitalization: TextCapitalization.characters,
              decoration: const InputDecoration(labelText: 'Moneda base (ISO 4217)'),
              validator: (value) {
                final currency = value?.trim().toUpperCase() ?? '';
                if (!RegExp(r'^[A-Z]{3}$').hasMatch(currency)) {
                  return 'Introduce un código de moneda de tres letras.';
                }
                return null;
              },
            ),
            const SizedBox(height: 12),
            TextFormField(
              key: const Key('available-capital-field'),
              controller: _availableCapitalController,
              enabled: !widget.busy,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                labelText: 'Capital disponible (moneda base)',
                hintText: 'Opcional: 0–1.000.000.000.000',
              ),
              validator: (value) {
                final text = value?.trim().replaceAll(',', '.') ?? '';
                if (text.isEmpty) return null;
                final capital = double.tryParse(text);
                if (capital == null ||
                    !capital.isFinite ||
                    capital < 0 ||
                    capital > UserPreferences.maxAvailableCapital) {
                  return 'Introduce un capital entre 0 y 1.000.000.000.000, o déjalo vacío.';
                }
                return null;
              },
            ),
            const SizedBox(height: 12),
            TextFormField(
              key: const Key('max-drawdown-field'),
              controller: _drawdownController,
              enabled: !widget.busy,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                labelText: 'Drawdown máximo tolerable (%)',
                hintText: 'Opcional: 5–60',
              ),
              validator: (value) {
                final text = value?.trim() ?? '';
                if (text.isEmpty) return null;
                final drawdown = int.tryParse(text);
                if (drawdown == null || drawdown < 5 || drawdown > 60) {
                  return 'Introduce un drawdown entre 5% y 60%, o déjalo vacío.';
                }
                return null;
              },
            ),
            const SizedBox(height: 16),
            Wrap(
              spacing: 10,
              runSpacing: 8,
              children: [
                ElevatedButton.icon(
                  onPressed: widget.busy ? null : _submit,
                  icon: widget.busy
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.save_outlined),
                  label: const Text('GUARDAR'),
                ),
                OutlinedButton.icon(
                  onPressed: widget.busy ? null : widget.onReload,
                  icon: const Icon(Icons.refresh_rounded),
                  label: const Text('RECARGAR'),
                ),
                if (widget.onDelete != null)
                  TextButton.icon(
                    onPressed: widget.busy ? null : widget.onDelete,
                    icon: const Icon(Icons.delete_outline_rounded),
                    label: const Text('ELIMINAR'),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              widget.preferences == null
                  ? 'Aún no hay preferencias guardadas.'
                  : 'Preferencias cargadas desde almacenamiento cifrado.',
              style: const TextStyle(
                color: AthenaColors.primary,
                fontSize: 12,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
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
      padding: const EdgeInsets.all(20),
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
              color: AthenaColors.primary,
              fontSize: 12,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.8,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            account.displayName ?? account.email,
            style: const TextStyle(
              color: AthenaColors.text,
              fontSize: 22,
              fontWeight: FontWeight.bold,
            ),
          ),
          if (account.displayName != null) ...[
            const SizedBox(height: 4),
            Text(
              account.email,
              style: const TextStyle(color: AthenaColors.textSecondary),
            ),
          ],
          const SizedBox(height: 12),
          const Text(
            'La identidad se revalida contra el backend. Las preferencias sensibles solo se leen y escriben mediante la sesión autenticada.',
            style: TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 11,
              height: 1.4,
            ),
          ),
        ],
      ),
    );
  }
}

class _ProfileSection extends StatelessWidget {
  const _ProfileSection({
    required this.icon,
    required this.title,
    required this.description,
    required this.status,
  });

  final IconData icon;
  final String title;
  final String description;
  final String status;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AthenaColors.card,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AthenaColors.border),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: AthenaColors.primary),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    color: AthenaColors.text,
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 5),
                Text(
                  description,
                  style: const TextStyle(
                    color: AthenaColors.textSecondary,
                    height: 1.35,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  status,
                  style: const TextStyle(
                    color: AthenaColors.primary,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
