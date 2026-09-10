import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';

class ProfilePage extends StatelessWidget {
  const ProfilePage({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AthenaColors.background,
      appBar: AppBar(
        backgroundColor: AthenaColors.background,
        foregroundColor: AthenaColors.text,
        elevation: 0,
        title: const Text('PERFIL'),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(24),
          children: const [
            _ProfileIntro(),
            SizedBox(height: 16),
            _ProfileSection(
              icon: Icons.person_outline_rounded,
              title: 'Datos personales',
              description: 'Identidad y datos básicos del usuario.',
              status: 'Pendiente de persistencia segura',
            ),
            SizedBox(height: 12),
            _ProfileSection(
              icon: Icons.tune_rounded,
              title: 'Preferencias',
              description: 'Objetivos, horizonte y preferencias de inversión.',
              status: 'Pendiente de persistencia segura',
            ),
            SizedBox(height: 12),
            _ProfileSection(
              icon: Icons.shield_outlined,
              title: 'Perfil de riesgo',
              description: 'Configuración de tolerancia al riesgo y límites.',
              status: 'Pendiente de cuestionario validado',
            ),
            SizedBox(height: 12),
            _ProfileSection(
              icon: Icons.language_rounded,
              title: 'Idioma',
              description: 'Español es el idioma activo de la versión inicial.',
              status: 'Español',
            ),
          ],
        ),
      ),
    );
  }
}

class _ProfileIntro extends StatelessWidget {
  const _ProfileIntro();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: AthenaColors.card,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AthenaColors.border),
      ),
      child: const Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Tu espacio personal',
            style: TextStyle(
              color: AthenaColors.text,
              fontSize: 22,
              fontWeight: FontWeight.bold,
            ),
          ),
          SizedBox(height: 8),
          Text(
            'ATHENA usará este perfil para adaptar explicaciones y análisis. '
            'No se activará personalización sensible hasta disponer de '
            'persistencia y controles de privacidad adecuados.',
            style: TextStyle(
              color: AthenaColors.textSecondary,
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
