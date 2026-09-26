import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../../../../core/routing/app_routes.dart';
import '../../../../core/theme/athena_colors.dart';
import '../../../auth/services/athena_auth_service.dart';
import '../../../auth/services/auth_session.dart';

class WelcomePage extends StatefulWidget {
  const WelcomePage({super.key});

  @override
  State<WelcomePage> createState() => _WelcomePageState();
}

class _WelcomePageState extends State<WelcomePage> {
  final AthenaAuthService _authService = AthenaAuthService();
  bool _restoring = true;
  String? _restoreNotice;

  @override
  void initState() {
    super.initState();
    _restoreSession();
  }

  @override
  void dispose() {
    _authService.dispose();
    super.dispose();
  }

  Future<void> _restoreSession() async {
    final result = await AuthSession.instance.restore(
      validateToken: _authService.getMe,
      shouldDiscardToken: (error) => error is AuthSessionRejectedException,
    );
    if (!mounted) return;
    if (result == AuthSessionRestoreResult.restored) {
      Navigator.pushNamedAndRemoveUntil(
        context,
        AppRoutes.dashboard,
        (route) => false,
      );
      return;
    }
    setState(() {
      _restoring = false;
      _restoreNotice = result == AuthSessionRestoreResult.temporarilyUnavailable
          ? 'Hay una sesión protegida guardada, pero no se ha podido validar ahora. No se ha aceptado como autenticada ni se ha borrado por un fallo transitorio.'
          : result == AuthSessionRestoreResult.rejected
              ? 'La sesión guardada había caducado o fue revocada y se ha eliminado del almacenamiento seguro.'
              : null;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AthenaColors.background,
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 40),
              child: _restoring
                  ? const Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        CircularProgressIndicator(),
                        SizedBox(height: 18),
                        Text(
                          'Validando sesión protegida…',
                          style: TextStyle(color: AthenaColors.textSecondary),
                        ),
                      ],
                    )
                  : Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        SvgPicture.asset(
                          'assets/branding/athena_logo_full.svg',
                          width: 420,
                          height: 260,
                          fit: BoxFit.contain,
                        ),
                        const SizedBox(height: 45),
                        if (_restoreNotice != null) ...[
                          Text(
                            _restoreNotice!,
                            textAlign: TextAlign.center,
                            style: const TextStyle(
                              color: AthenaColors.textSecondary,
                              fontSize: 11,
                              height: 1.4,
                            ),
                          ),
                          const SizedBox(height: 14),
                        ],
                        SizedBox(
                          width: 280,
                          height: 54,
                          child: ElevatedButton(
                            onPressed: () => Navigator.pushNamed(
                              context,
                              AppRoutes.login,
                            ),
                            child: const Text(
                              'ENTRAR CON CUENTA',
                              style: TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.bold,
                                letterSpacing: 1.1,
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(height: 12),
                        TextButton(
                          onPressed: () => Navigator.pushReplacementNamed(
                            context,
                            AppRoutes.dashboard,
                          ),
                          child: const Text('Continuar como invitado'),
                        ),
                        const SizedBox(height: 10),
                        const Text(
                          'El modo invitado permite explorar ATHENA sin asociar datos personales. Las funciones de perfil protegido requieren una cuenta autenticada.',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            color: AthenaColors.textSecondary,
                            fontSize: 11,
                            height: 1.4,
                          ),
                        ),
                      ],
                    ),
            ),
          ),
        ),
      ),
    );
  }
}
