import 'package:flutter/material.dart';

import '../../../../../core/theme/athena_colors.dart';
import '../../../../../core/theme/athena_radius.dart';

class MySpacePanel extends StatelessWidget {
  const MySpacePanel({super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 245,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AthenaColors.card,
        borderRadius: BorderRadius.circular(AthenaRadius.lg),
        border: Border.all(
          color: AthenaColors.border,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'MI ESPACIO',
            style: TextStyle(
              color: AthenaColors.text,
              fontSize: 20,
              fontWeight: FontWeight.bold,
            ),
          ),

          const SizedBox(height: 10),

          _row(
            'Patrimonio',
            '52.430 €',
            '+1,82 % hoy',
            Colors.green,
          ),

          _divider(),

          _row(
            'Liquidez',
            '8.250 €',
            'Disponible',
            Colors.white,
          ),

          _divider(),

          _row(
            'Rentabilidad',
            '+18,70 %',
            'Últimos 12 meses',
            Colors.green,
          ),

          _divider(),

          _row(
            'Riesgo',
            'Bajo',
            'Volatilidad 12 %',
            Colors.green,
          ),

          const Spacer(),

          const SizedBox(height: 8),

          SizedBox(
            width: double.infinity,
            height: 40,
            child: ElevatedButton(
              onPressed: () {
                Navigator.pushNamed(context, '/portfolio');
              },
              child: const Text(
                'Ver cartera',
              ),
            ),
          ),
        ],
      ),
    );
  }

  static Widget _divider() {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Container(
        height: 1,
        color: AthenaColors.border,
      ),
    );
  }

  static Widget _row(
    String title,
    String value,
    String subtitle,
    Color valueColor,
  ) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: const TextStyle(
            color: AthenaColors.textSecondary,
            fontSize: 12,
          ),
        ),

        const SizedBox(height: 1),

        Text(
          value,
          style: TextStyle(
            color: valueColor,
            fontSize: 20,
            fontWeight: FontWeight.bold,
          ),
        ),

        const SizedBox(height: 1),

        Text(
          subtitle,
          style: const TextStyle(
            color: AthenaColors.textSecondary,
            fontSize: 11,
          ),
        ),
      ],
    );
  }
}