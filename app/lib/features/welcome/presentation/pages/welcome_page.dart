import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../../../../../core/routing/app_routes.dart';
import '../../../../../core/theme/athena_colors.dart';

class WelcomePage extends StatelessWidget {
  const WelcomePage({super.key});

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
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  SvgPicture.asset(
                    'assets/branding/athena_logo_full.svg',
                    width: 420,
                    height: 260,
                    fit: BoxFit.contain,
                  ),
                  const SizedBox(height: 45),
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
                    'El modo invitado permite explorar ATHENA sin asociar datos personales. '
                    'Las funciones de perfil protegido requieren una cuenta autenticada.',
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
