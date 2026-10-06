import 'package:flutter/material.dart';

import '../../../recommendations/data/datasources/athena_backend_professional_dossier_data_source.dart';
import '../../../recommendations/di/recommendation_dependencies.dart';

class ProfessionalStockResearchPage extends StatefulWidget {
  final String symbol;
  final AthenaBackendProfessionalDossierDataSource? dataSource;
  const ProfessionalStockResearchPage({super.key, required this.symbol, this.dataSource});
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

  Future<ProfessionalDossier> _load() {
    final symbol = widget.symbol.trim().toUpperCase();
    if (symbol.isEmpty) {
      return Future.error(const FormatException('El símbolo es obligatorio para investigar una acción.'));
    }
    return _dataSource.getLatest(symbol: symbol);
  }

  void _retry() => setState(() => _future = _load());

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
            if (snapshot.hasError || !snapshot.hasData || !snapshot.data!.isSafe) {
              return _ResearchError(onRetry: _retry);
            }
            return _ResearchBody(symbol: symbol, dossier: snapshot.data!);
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
  const _ResearchBody({required this.symbol, required this.dossier});

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
        const SizedBox(height: 20),
        ...modules.map((name) {
          final module = dossier.modules[name]!;
          return Card(
            child: ListTile(
              title: Text(_label(name)),
              subtitle: Text(module.reason),
              trailing: Text(module.status),
            ),
          );
        }),
      ],
    );
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
