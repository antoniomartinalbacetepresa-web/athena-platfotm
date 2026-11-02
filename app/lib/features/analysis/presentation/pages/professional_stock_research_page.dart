import 'package:flutter/material.dart';

import '../../../recommendations/data/datasources/athena_backend_professional_dossier_data_source.dart';
import '../../../recommendations/di/recommendation_dependencies.dart';

class ProfessionalStockResearchPage extends StatefulWidget {
  final String symbol;
  /// Optional canonical DB row identity supplied by a trusted market flow.
  final int? instrumentId;
  final AthenaBackendProfessionalDossierDataSource? dataSource;
  const ProfessionalStockResearchPage({super.key, required this.symbol, this.instrumentId, this.dataSource});
  @override
  State<ProfessionalStockResearchPage> createState() => _ProfessionalStockResearchPageState();
}

class _ProfessionalStockResearchPageState extends State<ProfessionalStockResearchPage> {
  RecommendationDependencies? _dependencies;
  late AthenaBackendProfessionalDossierDataSource _dataSource;
  late Future<ProfessionalDossier> _future;

  @override
  void initState() {
    super.initState();
    if (widget.dataSource != null) {
      _dataSource = widget.dataSource!;
    } else {
      _dependencies = RecommendationDependencies.create();
      _dataSource = _dependencies!.professionalDossierDataSource;
    }
    _future = _load();
  }

  @override
  void didUpdateWidget(covariant ProfessionalStockResearchPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    final sourceChanged = !identical(oldWidget.dataSource, widget.dataSource);
    if (!sourceChanged && oldWidget.symbol == widget.symbol &&
        oldWidget.instrumentId == widget.instrumentId) {
      return;
    }

    final oldDependencies = _dependencies;
    if (sourceChanged) {
      if (widget.dataSource != null) {
        _dependencies = null;
        _dataSource = widget.dataSource!;
      } else {
        _dependencies = RecommendationDependencies.create();
        _dataSource = _dependencies!.professionalDossierDataSource;
      }
    }
    // FutureBuilder must subscribe to the new identity/source generation.
    // An old response cannot become the dossier under a new page heading.
    // didUpdateWidget is followed by a build; no setState is required here.
    _future = _load();
    if (sourceChanged) oldDependencies?.dispose();
  }

  Future<ProfessionalDossier> _load() {
    final symbol = widget.symbol.trim().toUpperCase();
    if (symbol.isEmpty || (widget.instrumentId != null && widget.instrumentId! <= 0)) {
      return Future.error(const FormatException('El símbolo es obligatorio para investigar una acción.'));
    }
    return _dataSource.getLatest(symbol: symbol, instrumentId: widget.instrumentId);
  }

  void _retry() {
    setState(() {
      _future = _load();
    });
  }

  @override
  void dispose() {
    _dependencies?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final symbol = widget.symbol.trim().toUpperCase();
    return Scaffold(
      backgroundColor: const Color(0xFF081423),
      appBar: AppBar(
        backgroundColor: const Color(0xFF081423),
        foregroundColor: Colors.white,
        title: Semantics(header: true, child: Text('ANÁLISIS ATHENA · $symbol')),
        actions: [
          IconButton(
            tooltip: 'Actualizar dossier profesional',
            onPressed: _retry,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: SafeArea(
        child: FutureBuilder<ProfessionalDossier>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return Center(
                child: Semantics(
                  liveRegion: true,
                  label: 'Cargando dossier profesional de ATHENA.',
                  child: CircularProgressIndicator(),
                ),
              );
            }
            if (snapshot.hasError ||
                !snapshot.hasData ||
                !snapshot.data!.isSafe ||
                snapshot.data!.symbol != symbol ||
                (widget.instrumentId != null &&
                    snapshot.data!.instrumentId != widget.instrumentId) ||
                snapshot.data!.asOf.isAfter(DateTime.now().toUtc())) {
              return _ResearchError(onRetry: _retry);
            }
            return _ResearchBody(symbol: symbol, dossier: snapshot.data!,
              requestedInstrumentId: widget.instrumentId);
          },
        ),
      ),
    );
  }
}

class _ResearchError extends StatelessWidget {
  final VoidCallback onRetry;
  const _ResearchError({required this.onRetry});
  @override
  Widget build(BuildContext context) {
    return Center(
      child: Semantics(
        liveRegion: true,
        container: true,
        label: 'No se puede verificar el dossier profesional. ATHENA no mostrará análisis no verificado.',
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'ANÁLISIS NO VERIFICABLE',
              key: Key('professional-research-error'),
              style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 12),
            ElevatedButton(onPressed: onRetry, child: const Text('REINTENTAR')),
          ],
        ),
      ),
    );
  }
}

class _ResearchBody extends StatelessWidget {
  final String symbol;
  final ProfessionalDossier dossier;
  final int? requestedInstrumentId;
  const _ResearchBody({required this.symbol, required this.dossier,
    required this.requestedInstrumentId});

  @override
  Widget build(BuildContext context) {
    final modules = ProfessionalDossier.moduleNames.toList(growable: false);
    return ListView(
      key: const Key('professional-research-content'),
      padding: const EdgeInsets.all(24),
      children: [
        Semantics(
          container: true,
          label: 'Investigación de solo lectura. No constituye asesoramiento, no ejecuta órdenes, no habilita trading automático y no modifica automáticamente el weighting.',
          child: const ExcludeSemantics(
            child: Text(
              'Investigación verificable y de solo lectura. Sin órdenes, trading automático ni cambios automáticos de weighting.',
              key: Key('professional-research-safety-boundary'),
              style: TextStyle(color: Color(0xFF9FB2C7)),
            ),
          ),
        ),
        const SizedBox(height: 16),
        Text(
          '$symbol · corte PIT ${dossier.asOf.toUtc().toIso8601String()}',
          key: const Key('professional-research-pit-cutoff'),
          style: const TextStyle(color: Colors.white),
        ),
        const SizedBox(height: 8),
        Text(
          requestedInstrumentId == null
              ? 'Identidad canónica Market–ATHENA NO acreditada: consulta por símbolo.'
              : 'Identidad canónica vinculada: instrumento #$requestedInstrumentId.',
          key: const Key('professional-research-canonical-identity'),
          style: const TextStyle(color: Color(0xFF9FB2C7)),
        ),
        const SizedBox(height: 8),
        Semantics(
          liveRegion: true,
          child: Text(
            'Evidencia adjunta: ${dossier.modules.values.where((module) => module.evidence != null).length} de ${ProfessionalDossier.moduleNames.length} módulos. La presencia de evidencia no acredita validación independiente.',
            key: const Key('professional-research-evidence-coverage'),
            style: const TextStyle(color: Color(0xFF9FB2C7)),
          ),
        ),
        if (DateTime.now().toUtc().difference(dossier.asOf) >
            const Duration(hours: 24)) ...[
          const SizedBox(height: 8),
          const Text(
            'INVESTIGACIÓN HISTÓRICA: corte PIT de más de 24 horas. Actualizar no garantiza datos recientes.',
            key: Key('professional-research-stale-warning'),
            style: TextStyle(color: Color(0xFFFFD37A)),
          ),
        ],
        const SizedBox(height: 20),
        ...modules.map((name) {
          final module = dossier.modules[name]!;
          final provenance = module.evidence == null
              ? null
              : _provenanceSummary(module.evidence!);
          return Card(
            key: Key('professional-research-module-$name'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                ListTile(
                  title: Text(_label(name)),
                  subtitle: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(module.reason),
                      if (provenance != null) ...[
                        const SizedBox(height: 4),
                        Text(
                          provenance,
                          key: Key('professional-research-provenance-$name'),
                        ),
                      ],
                    ],
                  ),
                  trailing: Text(module.status),
                ),
                if (name == 'dividendTotalReturn' &&
                    module.dividendDiagnostics != null)
                  _DividendDiagnosticDetails(
                    diagnostics: module.dividendDiagnostics!,
                  ),
              ],
            ),
          );
        }),
      ],
    );
  }

  String? _provenanceSummary(Map<String, dynamic> evidence) {
    final cutoff = evidence['knowledgeCutoff']?.toString().trim();
    final provider = evidence['sourceProvider']?.toString().trim();
    final parts = <String>[];
    if (provider != null && provider.isNotEmpty) {
      parts.add('Fuente: $provider');
    }
    if (cutoff != null && cutoff.isNotEmpty) {
      parts.add('PIT: $cutoff');
    }
    return parts.isEmpty ? null : parts.join(' · ');
  }

  String _label(String name) {
    const labels = <String, String>{
      'expectationsGap': 'Expectations Gap',
      'reverseValuation': 'Valoración inversa',
      'scenarioAsymmetry': 'Escenarios bear/base/bull',
      'catalysts': 'Catalizadores',
      'thesisInvalidation': 'Invalidación de tesis',
      'factorRisk': 'Riesgo factorial',
      'performanceAttribution': 'Atribución',
      'investmentJournal': 'Journal',
      'devilsAdvocate': 'Devil’s Advocate',
      'athenaRadar': 'ATHENA Radar',
      'dividendTotalReturn': 'Dividendos y retorno total',
    };
    return labels[name] ?? name;
  }
}

class _DividendDiagnosticDetails extends StatelessWidget {
  final ProfessionalDividendDiagnostics diagnostics;

  const _DividendDiagnosticDetails({required this.diagnostics});

  String _percent(double? value) {
    if (value == null) return 'No disponible';
    final percentage = value * 100;
    return percentage.isFinite
        ? '${percentage.toStringAsFixed(2)} %'
        : 'No disponible';
  }

  String _frequency(String? value) {
    const labels = <String, String>{
      'none': 'Sin historial de dividendos',
      'insufficient_history': 'Historial insuficiente',
      'monthly': 'Mensual',
      'quarterly': 'Trimestral',
      'semiannual': 'Semestral',
      'annual': 'Anual',
      'irregular': 'Irregular',
    };
    return labels[value] ?? 'No disponible';
  }

  @override
  Widget build(BuildContext context) {
    final status = switch (diagnostics.status) {
      'diagnostic_ready' => 'Diagnóstico disponible',
      'no_dividend_history' => 'Sin historial de dividendos',
      _ => 'Evidencia de mercado insuficiente',
    };
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
      child: Semantics(
        container: true,
        label: 'Diagnóstico PIT descriptivo de dividendos y retorno total. '
            'No es una predicción ni autoriza recomendaciones u operaciones.',
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(status, key: const Key('professional-dividend-status')),
            Text('Frecuencia: ${_frequency(diagnostics.frequency)}'),
            Text(
              'Rentabilidad por dividendo histórica: ${_percent(diagnostics.trailingYield)}',
              key: const Key('professional-dividend-yield'),
            ),
            Text('Crecimiento histórico del dividendo: ${_percent(diagnostics.dividendGrowthRate)}'),
            Text('Estabilidad de pagos: ${_percent(diagnostics.paymentStabilityScore)}'),
            Text(
              'Retorno total histórico 60 días: ${_percent(diagnostics.totalReturn60d)}',
              key: const Key('professional-dividend-total-return'),
            ),
            Text('Payout sobre beneficios: ${_percent(diagnostics.earningsPayoutRatio)}'),
            Text('Payout sobre flujo de caja libre: ${_percent(diagnostics.fcfPayoutRatio)}'),
            Text('Sostenibilidad financiera: ${_percent(diagnostics.financialSustainabilityScore)}'),
          ],
        ),
      ),
    );
  }
}
