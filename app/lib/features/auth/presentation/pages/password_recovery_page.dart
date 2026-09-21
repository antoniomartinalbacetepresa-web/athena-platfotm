import 'package:flutter/material.dart';

import '../../../../core/routing/app_routes.dart';
import '../../../../core/theme/athena_colors.dart';
import '../../services/athena_auth_service.dart';

class PasswordRecoveryPage extends StatefulWidget {
  const PasswordRecoveryPage({
    super.key,
    this.initialToken,
    this.service,
  });

  final String? initialToken;
  final AthenaAuthService? service;

  @override
  State<PasswordRecoveryPage> createState() => _PasswordRecoveryPageState();
}

class _PasswordRecoveryPageState extends State<PasswordRecoveryPage> {
  final _emailController = TextEditingController();
  final _tokenController = TextEditingController();
  final _passwordController = TextEditingController();
  final _confirmPasswordController = TextEditingController();
  late final AthenaAuthService _service;
  late final bool _ownsService;
  bool _loading = false;
  bool _requestAccepted = false;
  bool _resetComplete = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _service = widget.service ?? AthenaAuthService();
    _ownsService = widget.service == null;
    final initialToken = widget.initialToken?.trim() ?? '';
    if (initialToken.isNotEmpty) {
      _tokenController.text = initialToken;
    }
  }

  @override
  void dispose() {
    _emailController.dispose();
    _tokenController.dispose();
    _passwordController.dispose();
    _confirmPasswordController.dispose();
    if (_ownsService) {
      _service.dispose();
    }
    super.dispose();
  }

  Future<void> _requestRecovery() async {
    if (_loading) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      await _service.requestPasswordRecovery(email: _emailController.text);
      if (!mounted) return;
      setState(() => _requestAccepted = true);
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error = 'No se pudo procesar la solicitud de recuperación. Inténtalo de nuevo más tarde.';
      });
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _resetPassword() async {
    if (_loading) return;
    final password = _passwordController.text;
    if (password != _confirmPasswordController.text) {
      setState(() => _error = 'Las contraseñas no coinciden.');
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      await _service.resetPassword(
        token: _tokenController.text,
        newPassword: password,
      );
      if (!mounted) return;
      _tokenController.clear();
      _passwordController.clear();
      _confirmPasswordController.clear();
      setState(() => _resetComplete = true);
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error = 'No se pudo restablecer la contraseña. Comprueba que el enlace siga siendo válido y vuelve a intentarlo.';
      });
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AthenaColors.background,
      appBar: AppBar(
        backgroundColor: AthenaColors.background,
        foregroundColor: AthenaColors.text,
        elevation: 0,
        title: const Text('RECUPERAR ACCESO'),
      ),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 460),
              child: Container(
                padding: const EdgeInsets.all(24),
                decoration: BoxDecoration(
                  color: AthenaColors.card,
                  borderRadius: BorderRadius.circular(18),
                  border: Border.all(color: AthenaColors.border),
                ),
                child: _resetComplete ? _buildCompleted() : _buildForm(),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildCompleted() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text(
          'Contraseña restablecida',
          textAlign: TextAlign.center,
          style: TextStyle(
            color: AthenaColors.primary,
            fontSize: 22,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 14),
        const Text(
          'Las sesiones anteriores quedan invalidadas por el backend. Inicia sesión de nuevo con tu nueva contraseña.',
          textAlign: TextAlign.center,
          style: TextStyle(color: AthenaColors.textSecondary, height: 1.4),
        ),
        const SizedBox(height: 22),
        ElevatedButton(
          onPressed: () => Navigator.pushNamedAndRemoveUntil(
            context,
            AppRoutes.login,
            (route) => false,
          ),
          child: const Text('VOLVER A INICIAR SESIÓN'),
        ),
      ],
    );
  }

  Widget _buildForm() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text(
          'Recuperación segura',
          textAlign: TextAlign.center,
          style: TextStyle(
            color: AthenaColors.primary,
            fontSize: 22,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 10),
        const Text(
          'Solicita un enlace para tu email. La respuesta no revelará si existe una cuenta asociada.',
          textAlign: TextAlign.center,
          style: TextStyle(color: AthenaColors.textSecondary, height: 1.4),
        ),
        const SizedBox(height: 22),
        TextField(
          key: const Key('recovery-email'),
          controller: _emailController,
          keyboardType: TextInputType.emailAddress,
          autofillHints: const [AutofillHints.email],
          decoration: const InputDecoration(labelText: 'Email'),
        ),
        const SizedBox(height: 12),
        ElevatedButton(
          key: const Key('recovery-request'),
          onPressed: _loading ? null : _requestRecovery,
          child: const Text('ENVIAR INSTRUCCIONES'),
        ),
        if (_requestAccepted) ...[
          const SizedBox(height: 12),
          const Text(
            'Si existe una cuenta válida para ese email, recibirás instrucciones de recuperación.',
            key: Key('recovery-generic-success'),
            style: TextStyle(color: AthenaColors.textSecondary, height: 1.35),
          ),
        ],
        const SizedBox(height: 28),
        const Divider(),
        const SizedBox(height: 20),
        const Text(
          'Restablecer contraseña',
          style: TextStyle(
            color: AthenaColors.text,
            fontWeight: FontWeight.w700,
            fontSize: 16,
          ),
        ),
        const SizedBox(height: 12),
        TextField(
          key: const Key('recovery-token'),
          controller: _tokenController,
          autocorrect: false,
          enableSuggestions: false,
          decoration: const InputDecoration(labelText: 'Token del enlace'),
        ),
        const SizedBox(height: 12),
        TextField(
          key: const Key('recovery-password'),
          controller: _passwordController,
          obscureText: true,
          autofillHints: const [AutofillHints.newPassword],
          decoration: const InputDecoration(
            labelText: 'Nueva contraseña',
            helperText: 'Entre 12 y 256 caracteres',
          ),
        ),
        const SizedBox(height: 12),
        TextField(
          key: const Key('recovery-password-confirm'),
          controller: _confirmPasswordController,
          obscureText: true,
          autofillHints: const [AutofillHints.newPassword],
          onSubmitted: (_) => _resetPassword(),
          decoration: const InputDecoration(labelText: 'Confirmar contraseña'),
        ),
        if (_error != null) ...[
          const SizedBox(height: 14),
          Text(
            _error!,
            key: const Key('recovery-error'),
            style: const TextStyle(color: AthenaColors.danger),
          ),
        ],
        const SizedBox(height: 18),
        ElevatedButton(
          key: const Key('recovery-reset'),
          onPressed: _loading ? null : _resetPassword,
          child: _loading
              ? const SizedBox(
                  width: 22,
                  height: 22,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('RESTABLECER CONTRASEÑA'),
        ),
        const SizedBox(height: 10),
        TextButton(
          onPressed: _loading
              ? null
              : () => Navigator.pushNamedAndRemoveUntil(
                    context,
                    AppRoutes.login,
                    (route) => false,
                  ),
          child: const Text('Volver al inicio de sesión'),
        ),
      ],
    );
  }
}
