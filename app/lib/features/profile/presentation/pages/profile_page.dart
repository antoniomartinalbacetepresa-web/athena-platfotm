import 'package:flutter/material.dart';

import '../../../../core/routing/app_routes.dart';
import '../../../../core/theme/athena_colors.dart';
import '../../../auth/models/auth_account.dart';
import '../../../auth/services/athena_auth_service.dart';
import '../../../auth/services/auth_session.dart';

class ProfilePage extends StatefulWidget {
  const ProfilePage({super.key});

  @override
  State<ProfilePage> createState() => _ProfilePageState();
}

class _ProfilePageState extends State<ProfilePage> {
  final AthenaAuthService _service = AthenaAuthService();
  bool _checking = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _refreshAuthenticatedAccount();
  }

  @override
  void dispose() {
    _service.dispose();
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
      final account = await _service.getMe(token);
      AuthSession.instance.establish(accessToken: token, account: account);
    } catch (_) {
      AuthSession.instance.clear();
      _error = 'La sesión ha caducado o ya no es válida.';
    } finally {
      if (mounted) setState(() => _checking = false);
    }
  }

  void _logout() {
    AuthSession.instance.clear();
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
                    onRefresh: _refreshAuthenticatedAccount,
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
                      'Estás usando ATHENA como invitado. Inicia sesión para acceder a datos personales y futuras preferencias protegidas.',
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
    required this.onRefresh,
    required this.onLogout,
  });

  final AuthAccount account;
  final Future<void> Function() onRefresh;
  final VoidCallback onLogout;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        _IdentityCard(account: account),
        const SizedBox(height: 16),
        const _ProfileSection(
          icon: Icons.tune_rounded,
          title: 'Preferencias',
          description: 'Objetivos, horizonte y preferencias de inversión.',
          status: 'Bloqueado hasta persistencia cifrada',
        ),
        const SizedBox(height: 12),
        const _ProfileSection(
          icon: Icons.shield_outlined,
          title: 'Perfil de riesgo',
          description: 'Configuración de tolerancia al riesgo y límites.',
          status: 'Pendiente de cuestionario validado y almacenamiento cifrado',
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
          onPressed: onRefresh,
          icon: const Icon(Icons.refresh_rounded),
          label: const Text('VALIDAR SESIÓN'),
        ),
        const SizedBox(height: 10),
        TextButton.icon(
          onPressed: onLogout,
          icon: const Icon(Icons.logout_rounded),
          label: const Text('CERRAR SESIÓN'),
        ),
      ],
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
            'La identidad se vuelve a validar contra /api/v1/auth/me. El token no se persiste en almacenamiento local en esta fase.',
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
