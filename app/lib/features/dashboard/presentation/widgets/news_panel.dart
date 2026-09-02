import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import 'base/athena_card.dart';

class NewsPanel extends StatelessWidget {
  const NewsPanel({super.key});

  @override
  Widget build(BuildContext context) {
    return AthenaCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'NOTICIAS',
            style: TextStyle(
              color: AthenaColors.text,
              fontSize: 22,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 18),
          Expanded(
            child: Center(
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(
                      Icons.article_outlined,
                      color: AthenaColors.textSecondary,
                      size: 36,
                    ),
                    const SizedBox(height: 12),
                    const Text(
                      'Feed real pendiente de integración',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        color: AthenaColors.text,
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 8),
                    const Text(
                      'ATHENA no mostrará titulares de ejemplo como si fueran '
                      'noticias actuales. Este panel se habilitará cuando el '
                      'feed real incluya fuente, fecha y trazabilidad.',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        color: AthenaColors.textSecondary,
                        fontSize: 12,
                        height: 1.4,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
