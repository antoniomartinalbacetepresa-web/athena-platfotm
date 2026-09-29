import 'package:flutter/material.dart';

import '../controllers/athena_synthesis_controller.dart';

class AthenaSynthesisPanel extends StatelessWidget {
  final AthenaSynthesisController controller;

  const AthenaSynthesisPanel({super.key, required this.controller});

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: controller,
      builder: (context, _) {
        if (controller.isLoading) {
          return Center(
            key: const Key('athena-synthesis-loading'),
            child: Semantics(
              liveRegion: true,
              label: 'Cargando síntesis ATHENA verificada',
              child: const ExcludeSemantics(child: CircularProgressIndicator()),
            ),
          );
        }
        final error = controller.error;
        if (error != null) {
          return Center(
            key: const Key('athena-synthesis-error'),
            child: Semantics(
              liveRegion: true,
              label: 'Error: no se pudo verificar la síntesis ATHENA.',
              child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text('No se pudo verificar la síntesis ATHENA.'),
                const SizedBox(height: 8),
                FilledButton(
                  key: const Key('athena-synthesis-retry'),
                  onPressed: controller.retry,
                  child: const Text('Reintentar'),
                ),
              ],
              ),
            ),
          );
        }
        final synthesis = controller.synthesis;
        if (synthesis == null) {
          return const Center(
            key: Key('athena-synthesis-empty'),
            child: Text('Selecciona un ciclo de investigación verificado para consultar ATHENA.'),
          );
        }
        return SingleChildScrollView(
          key: const Key('athena-synthesis-content'),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Semantics(
                header: true,
                child: const Text(
                  'ATHENA AI',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
                ),
              ),
              const SizedBox(height: 12),
              Text(synthesis.summary, key: const Key('athena-synthesis-summary')),
              const SizedBox(height: 16),
              const Text('Por qué importa', style: TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 6),
              Text(synthesis.rationale, key: const Key('athena-synthesis-rationale')),
              const SizedBox(height: 16),
              const Text('Incertidumbres', style: TextStyle(fontWeight: FontWeight.bold)),
              ...synthesis.uncertainties.map(
                (item) => Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text('• $item'),
                ),
              ),
              const SizedBox(height: 16),
              Wrap(
                key: const Key('athena-synthesis-provenance'),
                spacing: 8,
                runSpacing: 8,
                children: [
                  if (synthesis.provenance.hasNews) const Chip(label: Text('News verificada')),
                  if (synthesis.provenance.hasInvestors) const Chip(label: Text('Investors verificado')),
                  Chip(label: Text('${synthesis.evidenceIds.length} evidencias')),
                ],
              ),
              const SizedBox(height: 12),
              Semantics(
                container: true,
                label:
                    'Síntesis informativa basada en evidencia verificada. Expone incertidumbres; no garantiza resultados, no ejecuta operaciones y no modifica automáticamente recomendaciones.',
                child: const ExcludeSemantics(
                  child: Text(
                    'Síntesis informativa: expone incertidumbres y no garantiza resultados; no ejecuta operaciones ni modifica automáticamente recomendaciones.',
                    key: Key('athena-synthesis-advisory-notice'),
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}
