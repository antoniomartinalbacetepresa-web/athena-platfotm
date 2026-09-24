import 'package:flutter/material.dart';

import '../../../../core/accessibility/accessible_status_message.dart';
import '../news_synthesis_controller.dart';

class NewsSynthesisPanel extends StatelessWidget {
  final NewsSynthesisController controller;

  const NewsSynthesisPanel({super.key, required this.controller});

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: controller,
      builder: (context, _) {
        if (controller.loading) {
          return Center(
            child: Semantics(
              liveRegion: true,
              label: 'Cargando síntesis verificada de noticias',
              child: const ExcludeSemantics(child: CircularProgressIndicator()),
            ),
          );
        }
        if (controller.error != null) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const AccessibleStatusMessage(
                key: Key('news-synthesis-error-status'),
                message: 'La síntesis verificada de noticias no está disponible.',
                semanticLabel: 'Error: la síntesis verificada de noticias no está disponible.',
                style: TextStyle(),
              ),
              const SizedBox(height: 8),
              OutlinedButton(
                onPressed: controller.retry,
                child: const Text('Reintentar'),
              ),
            ],
          );
        }
        final synthesis = controller.synthesis;
        if (synthesis == null || synthesis.items.isEmpty) {
          return const AccessibleStatusMessage(
            key: Key('news-synthesis-empty-status'),
            message: 'No hay noticias sintetizadas verificadas disponibles.',
            semanticLabel: 'No hay noticias sintetizadas verificadas disponibles.',
            style: TextStyle(),
          );
        }
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Semantics(
              header: true,
              child: Text(
                'ANÁLISIS ATHENA DE NOTICIAS',
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
            const SizedBox(height: 6),
            Semantics(
              container: true,
              label: 'Síntesis informativa basada en evidencia point-in-time. No es una recomendación de inversión y no ejecuta operaciones.',
              child: const ExcludeSemantics(
                child: Text(
                  'Resumen e impacto estimados por un modelo externo validado contra evidencia PIT. No es una recomendación de inversión.',
                ),
              ),
            ),
            const SizedBox(height: 12),
            for (final item in synthesis.items) ...[
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${item.symbol} · ${item.importance.toUpperCase()}',
                        style: Theme.of(context).textTheme.titleSmall,
                      ),
                      const SizedBox(height: 8),
                      Text(item.summary),
                      const SizedBox(height: 8),
                      Text(
                        'Impacto estimado: ${item.impactDirection} · '
                        'magnitud ${(item.impactMagnitude * 100).round()}% · '
                        'confianza ${(item.confidence * 100).round()}%',
                      ),
                      const SizedBox(height: 6),
                      Text(
                        'Fuente: ${item.publisher} · Modelo: '
                        '${item.modelProvider}/${item.modelName} ${item.modelVersion}',
                      ),
                      SelectableText(
                        item.sourceRef,
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 8),
            ],
          ],
        );
      },
    );
  }
}
