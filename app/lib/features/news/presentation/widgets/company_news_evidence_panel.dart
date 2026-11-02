import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../models/company_news_evidence.dart';
import '../../services/athena_backend_company_news_evidence_service.dart';

/// Explicitly separates company-specific lexical evidence from global synthesis.
class CompanyNewsEvidencePanel extends StatefulWidget {
  final String symbol;
  final String companyName;
  final Future<CompanyNewsEvidence> Function(String symbol, String companyName)?
      loadEvidence;

  const CompanyNewsEvidencePanel({
    super.key, required this.symbol, required this.companyName,
    this.loadEvidence,
  });

  @override
  State<CompanyNewsEvidencePanel> createState() => _CompanyNewsEvidencePanelState();
}

class _CompanyNewsEvidencePanelState extends State<CompanyNewsEvidencePanel> {
  late final AthenaBackendCompanyNewsEvidenceService _service;
  late Future<CompanyNewsEvidence> _future;

  Future<CompanyNewsEvidence> _load() => widget.loadEvidence != null
      ? widget.loadEvidence!(widget.symbol, widget.companyName)
      : _service.getEvidence(symbol: widget.symbol, companyName: widget.companyName);

  @override
  void initState() {
    super.initState();
    _service = AthenaBackendCompanyNewsEvidenceService();
    _future = Future<CompanyNewsEvidence>.delayed(Duration.zero, _load);
  }

  @override
  void didUpdateWidget(covariant CompanyNewsEvidencePanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.symbol != widget.symbol ||
        oldWidget.companyName != widget.companyName ||
        !identical(oldWidget.loadEvidence, widget.loadEvidence)) {
      _future = Future<CompanyNewsEvidence>.delayed(Duration.zero, _load);
    }
  }

  void _refresh() => setState(() {
    _future = Future<CompanyNewsEvidence>.delayed(Duration.zero, _load);
  });

  @override
  void dispose() {
    _service.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Semantics(header: true, child: const Text(
        'EVIDENCIA EMPRESARIAL PARA ATHENA RADAR',
        key: Key('company-news-evidence-heading'),
        style: TextStyle(color: AthenaColors.text, fontWeight: FontWeight.bold),
      )),
      const Text(
        'Titulares seleccionados por coincidencia textual. No verifican identidad '
        'del emisor, veracidad, licencias ni persistencia PIT. Sin puntuación, '
        'recomendaciones ni operaciones automáticas.',
        key: Key('company-news-evidence-boundary'),
        style: TextStyle(color: AthenaColors.textSecondary, fontSize: 11),
      ),
      FutureBuilder<CompanyNewsEvidence>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const LinearProgressIndicator(
              key: Key('company-news-evidence-loading'),
            );
          }
          if (snapshot.hasError || !snapshot.hasData) {
            return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('Evidencia empresarial no disponible.',
                key: Key('company-news-evidence-error'),
                style: TextStyle(color: AthenaColors.textSecondary)),
              TextButton(onPressed: _refresh, child: const Text('Reintentar evidencia')),
            ]);
          }
          final evidence = snapshot.data!;
          // Injected loaders are untrusted, just like external JSON.
          if (evidence.symbol != widget.symbol ||
              evidence.companyName != widget.companyName ||
              evidence.retrievedAt.isAfter(DateTime.now().toUtc()) ||
              evidence.items.any((item) =>
                  item.availableAt.isAfter(evidence.retrievedAt) ||
                  item.publishedAt.isAfter(item.availableAt))) {
            return const Text('Evidencia empresarial contradictoria.',
              key: Key('company-news-evidence-error'),
              style: TextStyle(color: AthenaColors.textSecondary));
          }
          return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(
              '${evidence.symbol} · ${evidence.items.length} aceptadas · '
              '${evidence.rejectedCount} descartadas · ${evidence.provider} · '
              'recuperado ${evidence.retrievedAt.toIso8601String()}',
              key: const Key('company-news-evidence-provenance'),
              style: const TextStyle(color: AthenaColors.textSecondary, fontSize: 11),
            ),
            if (DateTime.now().toUtc().difference(evidence.retrievedAt) >
                const Duration(hours: 24))
              const Text('Evidencia antigua: más de 24 horas.',
                key: Key('company-news-evidence-stale'),
                style: TextStyle(color: AthenaColors.textSecondary)),
            if (evidence.items.isEmpty)
              const Text('No hay titulares empresariales aceptables.',
                key: Key('company-news-evidence-empty'),
                style: TextStyle(color: AthenaColors.textSecondary)),
            for (final item in evidence.items)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(item.summary, style: const TextStyle(color: AthenaColors.text)),
                  Text('${item.publisher} · publicado ${item.publishedAt.toIso8601String()}'
                    ' · disponible ${item.availableAt.toIso8601String()}',
                    style: const TextStyle(color: AthenaColors.textSecondary, fontSize: 11)),
                  SelectableText(item.sourceUrl,
                    style: const TextStyle(color: AthenaColors.textSecondary, fontSize: 11)),
                ]),
              ),
            TextButton(onPressed: _refresh, child: const Text('Actualizar evidencia')),
          ]);
        },
      ),
    ],
  );
}
