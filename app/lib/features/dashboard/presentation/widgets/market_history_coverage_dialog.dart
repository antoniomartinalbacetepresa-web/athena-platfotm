import 'package:flutter/material.dart';

import '../../../analysis/models/market_history_coverage.dart';
import '../../../analysis/services/athena_readiness_service.dart';

/// Read-only persisted PIT measurement, reconciled with the readiness snapshot.
class MarketHistoryCoverageDialog extends StatefulWidget {
  const MarketHistoryCoverageDialog({
    super.key,
    required this.service,
    required this.asOf,
    required this.expectedEligible,
    required this.expectedCurrent,
  });

  final AthenaReadinessService service;
  final DateTime asOf;
  final int expectedEligible;
  final int expectedCurrent;

  @override
  State<MarketHistoryCoverageDialog> createState() =>
      _MarketHistoryCoverageDialogState();
}

class _MarketHistoryCoverageDialogState
    extends State<MarketHistoryCoverageDialog> {
  late Future<MarketHistoryCoverage> _future;

  @override
  void initState() {
    super.initState();
    _future = _request();
  }

  @override
  void didUpdateWidget(covariant MarketHistoryCoverageDialog oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.service != widget.service ||
        !oldWidget.asOf.isAtSameMomentAs(widget.asOf) ||
        oldWidget.expectedEligible != widget.expectedEligible ||
        oldWidget.expectedCurrent != widget.expectedCurrent) {
      _future = _request();
    }
  }

  Future<MarketHistoryCoverage> _request() =>
      widget.service.getMarketHistoryCoverage(asOf: widget.asOf);

  void _reload() {
    setState(() {
      _future = _request();
    });
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('Cobertura histórica persistida PIT'),
        content: SizedBox(
          width: 520,
          height: 320,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Medición de solo lectura. No acredita cobertura productiva, '
                'no autoriza ponderaciones y no ejecuta órdenes ni backfill.',
              ),
              const SizedBox(height: 12),
              Expanded(
                child: FutureBuilder<MarketHistoryCoverage>(
                  future: _future,
                  builder: (context, snapshot) {
                    if (snapshot.connectionState == ConnectionState.waiting) {
                      return const Center(child: CircularProgressIndicator());
                    }
                    if (snapshot.hasError || snapshot.data == null) {
                      return Center(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const Text('Cobertura PIT no disponible.'),
                            TextButton(
                              onPressed: _reload,
                              child: const Text('Reintentar cobertura'),
                            ),
                          ],
                        ),
                      );
                    }
                    final coverage = snapshot.data!;
                    if (coverage.eligible != widget.expectedEligible ||
                        coverage.current != widget.expectedCurrent) {
                      return const Center(
                        child: Text(
                          'Cobertura persistida no coincide con readiness. '
                          'Diagnóstico bloqueado hasta nueva consulta.',
                        ),
                      );
                    }
                    return SingleChildScrollView(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('Corte PIT: ${coverage.asOf.toUtc().toIso8601String()}'),
                          const SizedBox(height: 8),
                          Text('Instrumentos con observaciones: ${coverage.covered}/${coverage.eligible}'),
                          Text('Histórico ≥365 días: ${coverage.deep}/${coverage.eligible}'),
                          Text(
                            'Histórico ≥365 días vigente: ${coverage.current}/${coverage.eligible}',
                            key: const Key('persisted-current-history-coverage'),
                          ),
                          Text('Observaciones PIT: ${coverage.observations}'),
                          const SizedBox(height: 8),
                          const Text('Fuentes de las observaciones:'),
                          if (coverage.sources.isEmpty)
                            const Text('Sin fuentes verificables en este corte.'),
                          for (final summary in coverage.sources) Text(summary),
                        ],
                      ),
                    );
                  },
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Cerrar'),
          ),
        ],
      );
}
