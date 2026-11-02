import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../../recommendations/data/datasources/athena_backend_professional_dossier_data_source.dart';
import '../../../recommendations/di/recommendation_dependencies.dart';

/// Read-only summary of the same independently fetched PIT dossier used by
/// professional research. A market quote is never promoted to PIT evidence.
class MarketResearchPreview extends StatefulWidget {
  final String symbol;
  final int? instrumentId;
  final Future<ProfessionalDossier> Function(String symbol, int? instrumentId)? loadDossier;
  final VoidCallback? onOpenFullResearch;

  const MarketResearchPreview({
    super.key,
    required this.symbol,
    this.instrumentId,
    this.loadDossier,
    this.onOpenFullResearch,
  });

  @override
  State<MarketResearchPreview> createState() => _MarketResearchPreviewState();
}

class _MarketResearchPreviewState extends State<MarketResearchPreview> {
  RecommendationDependencies? _dependencies;
  late Future<ProfessionalDossier> _future;

  @override
  void initState() {
    super.initState();
    _future = Future<ProfessionalDossier>.sync(_load);
  }

  Future<ProfessionalDossier> _load() {
    final symbol = widget.symbol.trim().toUpperCase();
    if (symbol.isEmpty || (widget.instrumentId != null && widget.instrumentId! <= 0)) {
      throw const FormatException('Identidad de investigación inválida.');
    }
    if (widget.loadDossier != null) {
      return widget.loadDossier!(symbol, widget.instrumentId);
    }
    _dependencies ??= RecommendationDependencies.create();
    return _dependencies!.professionalDossierDataSource.getLatest(
      symbol: symbol, instrumentId: widget.instrumentId,
    );
  }

  @override
  void didUpdateWidget(covariant MarketResearchPreview oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.symbol != widget.symbol ||
        oldWidget.instrumentId != widget.instrumentId ||
        !identical(oldWidget.loadDossier, widget.loadDossier)) {
      // FutureBuilder shows loading instead of an old issuer's evidence.
      _future = Future<ProfessionalDossier>.sync(_load);
    }
  }

  void _retry() {
    setState(() {
      _future = Future<ProfessionalDossier>.sync(_load);
    });
  }

  @override
  void dispose() {
    _dependencies?.dispose();
    super.dispose();
  }

  bool _valid(ProfessionalDossier dossier) {
    return dossier.isSafe &&
        dossier.symbol == widget.symbol.trim().toUpperCase() &&
        (widget.instrumentId == null || dossier.instrumentId == widget.instrumentId) &&
        !dossier.asOf.isAfter(DateTime.now().toUtc().add(const Duration(minutes: 5)));
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<ProfessionalDossier>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator(
            key: Key('market-research-loading'),
          ));
        }
        final dossier = snapshot.data;
        if (snapshot.hasError || dossier == null || !_valid(dossier)) {
          return Center(
            child: SingleChildScrollView(
              child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text(
                  'DOSIER ATHENA NO VERIFICABLE',
                  key: Key('market-research-error'),
                  style: TextStyle(color: AthenaColors.danger),
                ),
                TextButton(onPressed: _retry, child: const Text('REINTENTAR')),
              ],
              ),
            ),
          );
        }
        final count = dossier.modules.values.where((module) => module.evidence != null).length;
        final old = DateTime.now().toUtc().difference(dossier.asOf) >
            const Duration(hours: 24);
        return SingleChildScrollView(
          key: const Key('market-research-preview'),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
            Semantics(
              header: true,
              child: Text(
                'RESUMEN ATHENA · ${dossier.symbol}',
                style: const TextStyle(color: AthenaColors.text, fontWeight: FontWeight.bold),
              ),
            ),
            Text(
              'Corte PIT: ${dossier.asOf.toUtc().toIso8601String()}',
              key: const Key('market-research-pit'),
              style: const TextStyle(color: AthenaColors.textSecondary),
            ),
            Text(
              widget.instrumentId == null
                  ? 'Identidad por símbolo: sin vínculo canónico acreditado.'
                  : 'Registro interno ATHENA #${widget.instrumentId}; identidad externa no acreditada.',
              key: const Key('market-research-identity'),
              style: const TextStyle(color: AthenaColors.textSecondary),
            ),
            Text(
              'Evidencia adjunta: $count de ${ProfessionalDossier.moduleNames.length} módulos; '
              'no implica verificación independiente.',
              key: const Key('market-research-evidence-count'),
              style: const TextStyle(color: AthenaColors.textSecondary),
            ),
            Text(
              'Riesgo factorial: ${dossier.modules['factorRisk']!.status} · '
              'Valoración inversa: ${dossier.modules['reverseValuation']!.status}',
              key: const Key('market-research-module-status'),
              style: const TextStyle(color: AthenaColors.textSecondary),
            ),
            if (old)
              const Text(
                'INVESTIGACIÓN HISTÓRICA: corte PIT de más de 24 horas.',
                key: Key('market-research-stale'),
                style: TextStyle(color: Color(0xFFFFD37A)),
              ),
            const Text(
              'Investigación independiente de la cotización y las noticias. '
              'Solo lectura; sin asesoramiento, órdenes ni trading automático.',
              key: Key('market-research-safety-boundary'),
              style: TextStyle(color: AthenaColors.textSecondary),
            ),
            if (widget.onOpenFullResearch != null)
              OutlinedButton(
                key: const Key('market-research-open-full'),
                onPressed: widget.onOpenFullResearch,
                child: const Text('ABRIR DOSIER COMPLETO'),
              ),
            ],
          ),
        );
      },
    );
  }
}
