import 'package:flutter/material.dart';

import '../../../analysis/models/market_history_gaps.dart';
import '../../../analysis/services/athena_readiness_service.dart';

/// Diagnostic drill-down only: never fetches history or changes market state.
class MarketHistoryGapsDialog extends StatefulWidget {
  const MarketHistoryGapsDialog({
    super.key,
    required this.service,
    required this.asOf,
  });

  final AthenaReadinessService service;
  final DateTime asOf;

  @override
  State<MarketHistoryGapsDialog> createState() => _MarketHistoryGapsDialogState();
}

class _MarketHistoryGapsDialogState extends State<MarketHistoryGapsDialog> {
  static const _pageSize = 10;
  late Future<MarketHistoryGapsPage> _future;
  int _offset = 0;

  @override
  void initState() {
    super.initState();
    _future = _request(0);
  }

  @override
  void didUpdateWidget(covariant MarketHistoryGapsDialog oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.service != widget.service ||
        !oldWidget.asOf.isAtSameMomentAs(widget.asOf)) {
      _offset = 0;
      _future = _request(0);
    }
  }

  Future<MarketHistoryGapsPage> _request(int offset) =>
      widget.service.getMarketHistoryGaps(
        asOf: widget.asOf,
        limit: _pageSize,
        offset: offset,
      );

  void _load(int offset) {
    setState(() {
      _offset = offset;
      _future = _request(offset);
    });
  }

  Widget _page(MarketHistoryGapsPage page) {
    final counts = page.blockingByReason;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Bloqueados: ${page.totalBlockingCount} · corte PIT ${page.asOf.toUtc().toIso8601String()}',
          style: const TextStyle(fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 8),
        Text(
          'Sin datos: ${counts['no_observations']} · profundidad: ${counts['insufficient_span']} · discontinuos: ${counts['discontinuous_source']} · caducados: ${counts['stale_source']}',
          maxLines: 2,
        ),
        const SizedBox(height: 8),
        Expanded(
          child: page.items.isEmpty
              ? const Center(child: Text('Sin bloqueos en este corte PIT.'))
              : ListView.builder(
                  itemCount: page.items.length,
                  itemBuilder: (context, index) {
                    final item = page.items[index];
                    return ListTile(
                      dense: true,
                      title: Text(item.symbol),
                      subtitle: Text(
                        '${item.reasonLabel} · ${item.bestSourceProvider ?? 'sin fuente verificada'}',
                      ),
                    );
                  },
                ),
        ),
        Row(
          children: [
            Text('Desde ${page.offset + 1}'),
            const Spacer(),
            TextButton(
              onPressed: _offset > 0
                  ? () => _load(_offset >= _pageSize ? _offset - _pageSize : 0)
                  : null,
              child: const Text('Anterior'),
            ),
            TextButton(
              onPressed: _offset + page.items.length < page.totalBlockingCount
                  ? () => _load(_offset + _pageSize)
                  : null,
              child: const Text('Siguiente'),
            ),
          ],
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('Bloqueos del histórico PIT'),
        content: SizedBox(
          width: 540,
          height: 350,
          child: Column(
            children: [
              const Text(
                'Diagnóstico de datos persistidos: no acredita cobertura '
                'productiva, no recomienda operaciones y no ejecuta backfill.',
              ),
              const SizedBox(height: 12),
              Expanded(
                child: FutureBuilder<MarketHistoryGapsPage>(
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
                            const Text('Bloqueos PIT no disponibles.'),
                            TextButton(
                              onPressed: () => _load(_offset),
                              child: const Text('Reintentar diagnóstico'),
                            ),
                          ],
                        ),
                      );
                    }
                    return _page(snapshot.data!);
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
