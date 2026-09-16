import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../models/user_personalization.dart';

class UserPersonalizationPanel extends StatelessWidget {
  const UserPersonalizationPanel({
    super.key,
    required this.personalization,
    required this.busy,
    required this.onReload,
    this.error,
  });

  final UserPersonalization? personalization;
  final bool busy;
  final String? error;
  final Future<void> Function() onReload;

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('user-personalization-panel'),
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AthenaColors.card,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AthenaColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.auto_awesome_outlined, color: AthenaColors.primary),
              SizedBox(width: 12),
              Expanded(
                child: Text(
                  'Personalización de explicaciones',
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
            'Solo adapta la forma de presentar y explicar información. No modifica scores, recomendaciones, ponderaciones, aprendizaje ni activa operaciones.',
            key: Key('personalization-presentation-only-note'),
            style: TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 11,
              height: 1.35,
            ),
          ),
          const SizedBox(height: 14),
          if (busy)
            const Center(
              child: Padding(
                padding: EdgeInsets.all(12),
                child: CircularProgressIndicator(
                  key: Key('personalization-loading'),
                ),
              ),
            )
          else if (error != null) ...[
            Text(
              error!,
              key: const Key('personalization-error'),
              style: const TextStyle(color: Colors.redAccent, fontSize: 12),
            ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: onReload,
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('REINTENTAR'),
            ),
          ] else if (personalization == null) ...[
            const Text(
              'No configurada. Guarda tus preferencias protegidas para generar una proyección de presentación.',
              key: Key('personalization-not-configured'),
              style: TextStyle(color: AthenaColors.textSecondary, height: 1.35),
            ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: onReload,
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('COMPROBAR'),
            ),
          ] else ...[
            _PresentationRow(
              label: 'Nivel de detalle',
              value: _detailLabel(personalization!.presentation.detailLevel),
            ),
            _PresentationRow(
              label: 'Estilo',
              value: _styleLabel(personalization!.presentation.explanationStyle),
            ),
            _PresentationRow(
              label: 'Énfasis de riesgo',
              value: _riskLabel(personalization!.presentation.riskEmphasis),
            ),
            _PresentationRow(
              label: 'Horizonte',
              value: _horizonLabel(personalization!.presentation.horizonEmphasis),
            ),
            _PresentationRow(
              label: 'Liquidez',
              value: _liquidityLabel(personalization!.presentation.liquidityEmphasis),
            ),
            _PresentationRow(
              label: 'Objetivo',
              value: _objectiveLabel(personalization!.presentation.objectiveFocus),
            ),
            const SizedBox(height: 10),
            Text(
              'Contrato ${personalization!.schema} · ${personalization!.fingerprint.substring(0, 12)}…',
              key: const Key('personalization-contract-fingerprint'),
              style: const TextStyle(
                color: AthenaColors.textSecondary,
                fontSize: 10,
              ),
            ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: onReload,
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('ACTUALIZAR'),
            ),
          ],
        ],
      ),
    );
  }

  static String _detailLabel(String value) => switch (value) {
        'guided' => 'Guiado',
        'technical' => 'Técnico',
        _ => 'Estándar',
      };

  static String _styleLabel(String value) => switch (value) {
        'plain_language' => 'Lenguaje claro',
        'analytical' => 'Analítico',
        _ => 'Equilibrado',
      };

  static String _riskLabel(String value) => switch (value) {
        'high' => 'Alto',
        'low' => 'Bajo',
        _ => 'Estándar',
      };

  static String _horizonLabel(String value) => switch (value) {
        'short_term' => 'Corto plazo',
        'long_term' => 'Largo plazo',
        _ => 'Medio plazo',
      };

  static String _liquidityLabel(String value) => switch (value) {
        'low' => 'Baja',
        'medium' => 'Media',
        'high' => 'Alta',
        _ => 'No indicada',
      };

  static String _objectiveLabel(String value) => switch (value) {
        'capital_preservation' => 'Preservación de capital',
        'income' => 'Ingresos',
        'long_term_growth' => 'Crecimiento a largo plazo',
        _ => 'Crecimiento equilibrado',
      };
}

class _PresentationRow extends StatelessWidget {
  const _PresentationRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        children: [
          Expanded(
            child: Text(
              label,
              style: const TextStyle(color: AthenaColors.textSecondary),
            ),
          ),
          const SizedBox(width: 12),
          Text(
            value,
            style: const TextStyle(
              color: AthenaColors.primary,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}
