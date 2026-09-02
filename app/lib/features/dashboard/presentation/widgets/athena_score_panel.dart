import 'package:flutter/material.dart';

import '../../../../core/typography/athena_text.dart';
import '../../../../core/theme/athena_colors.dart';
import 'base/athena_card.dart';

class AthenaScorePanel extends StatelessWidget {
  const AthenaScorePanel({super.key});

  @override
  Widget build(BuildContext context) {
    return AthenaCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'ATHENA SCORE',
            style: AthenaText.h3,
          ),
          const SizedBox(height: 12),
          Expanded(
            child: Center(
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Container(
                      width: 88,
                      height: 88,
                      alignment: Alignment.center,
                      decoration: BoxDecoration(
                        color: AthenaColors.cardSecondary,
                        shape: BoxShape.circle,
                        border: Border.all(color: AthenaColors.border),
                      ),
                      child: const Icon(
                        Icons.hourglass_top_rounded,
                        color: AthenaColors.textSecondary,
                        size: 34,
                      ),
                    ),
                    const SizedBox(height: 12),
                    const Text(
                      'SIN CALIFICAR',
                      style: AthenaText.title,
                    ),
                    const SizedBox(height: 8),
                    const Padding(
                      padding: EdgeInsets.symmetric(horizontal: 8),
                      child: Text(
                        'El score se publicará únicamente cuando el motor real '
                        'disponga de evidencia suficiente y validada.',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          color: AthenaColors.textSecondary,
                          fontSize: 12,
                          height: 1.35,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
          const Divider(),
          const SizedBox(height: 8),
          const _StatusRow(label: 'Riesgo', value: 'Pendiente'),
          const SizedBox(height: 6),
          const _StatusRow(label: 'Potencial', value: 'Pendiente'),
          const SizedBox(height: 6),
          const _StatusRow(label: 'Producción', value: 'Bloqueada'),
        ],
      ),
    );
  }
}

class _StatusRow extends StatelessWidget {
  final String label;
  final String value;

  const _StatusRow({
    required this.label,
    required this.value,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(label, style: AthenaText.caption),
        Text(
          value,
          style: const TextStyle(
            color: AthenaColors.textSecondary,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }
}
