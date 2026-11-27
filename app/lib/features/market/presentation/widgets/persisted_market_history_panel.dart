import 'package:flutter/material.dart';

import '../../data/models/persisted_market_history.dart';
import '../../data/providers/athena_backend_market_data_provider.dart';
import '../../models/market_quote.dart';

typedef PersistedHistoryLoader = Future<PersistedMarketHistory> Function(
  MarketQuote quote, DateTime asOf,
);

/// Explicit local replay. Opening this surface never fetches a live provider.
class PersistedMarketHistoryPanel extends StatefulWidget {
  const PersistedMarketHistoryPanel({
    super.key, required this.quote, this.loadHistory,
  });

  final MarketQuote quote;
  final PersistedHistoryLoader? loadHistory;

  @override
  State<PersistedMarketHistoryPanel> createState() => _PersistedMarketHistoryPanelState();
}

class _PersistedMarketHistoryPanelState extends State<PersistedMarketHistoryPanel> {
  static const _backend = String.fromEnvironment(
    'ATHENA_BACKEND_URL', defaultValue: 'http://127.0.0.1:8000',
  );
  AthenaBackendMarketDataProvider? _provider;
  PersistedMarketHistory? _history;
  bool _loading = false;
  bool _failed = false;
  int _generation = 0;

  @override
  void didUpdateWidget(covariant PersistedMarketHistoryPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.quote.symbol != widget.quote.symbol ||
        oldWidget.quote.instrumentId != widget.quote.instrumentId ||
        oldWidget.quote.sourceProvider != widget.quote.sourceProvider ||
        oldWidget.quote.currency != widget.quote.currency ||
        oldWidget.loadHistory != widget.loadHistory) {
      _generation++;
      _history = null;
      _loading = false;
      _failed = false;
    }
  }

  @override
  void dispose() {
    _generation++;
    _provider?.dispose();
    super.dispose();
  }

  bool get _validSelection =>
      widget.quote.instrumentId != null && widget.quote.instrumentId! > 0 &&
      widget.quote.canonicalIdentityStatus == 'matched_internal_listing' &&
      (widget.quote.sourceProvider?.trim().isNotEmpty ?? false) &&
      widget.quote.currency?.length == 3 &&
      RegExp(r'^[A-Z]{3}$').hasMatch(widget.quote.currency ?? '');

  Future<PersistedMarketHistory> _fetch(MarketQuote quote, DateTime asOf) {
    final provider = _provider ??= AthenaBackendMarketDataProvider(baseUrl: _backend);
    return provider.getPersistedHistoricalData(
      instrumentId: quote.instrumentId!, symbol: quote.symbol,
      sourceProvider: quote.sourceProvider!,
      observedFrom: asOf.subtract(const Duration(days: 365)),
      observedTo: asOf, asOf: asOf,
    );
  }

  Future<void> _refresh() async {
    if (!_validSelection) return;
    final generation = ++_generation;
    final quote = widget.quote;
    final cutoff = DateTime.now().toUtc();
    setState(() {
      _history = null;
      _failed = false;
      _loading = true;
    });
    try {
      final history = await (widget.loadHistory ?? _fetch)(quote, cutoff)
          .timeout(const Duration(seconds: 15));
      if (!mounted || generation != _generation) return;
      if (history.asOf != cutoff || history.points.length > 400) {
        throw const FormatException('Incompatible history selection');
      }
      DateTime? previous;
      final ids = <int>{};
      for (final point in history.points) {
        final retrieved = point.retrievedAt;
        if (point.symbol != quote.symbol || point.instrumentId != quote.instrumentId ||
            point.sourceProvider != quote.sourceProvider || point.currency != quote.currency ||
            point.close == null || !point.close!.isFinite || point.close! <= 0 ||
            (point.volume != null && (!point.volume!.isFinite || point.volume! < 0)) ||
            point.historicalPointInTimeEligible != false ||
            point.realTimePriceVerified != false ||
            point.observationId == null || point.observationId! <= 0 ||
            !ids.add(point.observationId!) || retrieved == null ||
            retrieved.isAfter(cutoff) || point.timestamp.isAfter(retrieved) ||
            point.timestamp.isBefore(cutoff.subtract(const Duration(days: 365))) ||
            point.availableAt != retrieved ||
            (point.sourceTimestamp != null && point.sourceTimestamp!.isAfter(retrieved)) ||
            (previous != null && !point.timestamp.isAfter(previous))) {
          throw const FormatException('Untraceable persisted observation');
        }
        previous = point.timestamp;
      }
      setState(() {
        _history = history;
        _loading = false;
      });
    } catch (_) {
      if (!mounted || generation != _generation) return;
      // Provider/storage errors may contain secrets. Never render them.
      setState(() {
        _history = null;
        _failed = true;
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final history = _history;
    final isSynthetic = (history?.containsSyntheticEvidence ?? false) ||
        PersistedMarketHistory.classifySource(widget.quote.sourceProvider ?? '') ==
            PersistedMarketEvidenceKind.syntheticFixture;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Semantics(
          header: true,
          child: Text('Histórico guardado de ${widget.quote.symbol}'),
        ),
        Text('Proveedor: ${widget.quote.sourceProvider ?? "no identificado"} · '
            'instrumento #${widget.quote.instrumentId ?? "sin identificar"}'),
        if (isSynthetic)
          Semantics(
            liveRegion: true,
            child: const Text(
              'DATOS SINTÉTICOS DE PRUEBA. No representan precios reales '
              'ni acreditan funcionamiento con datos de mercado.',
              key: Key('persisted-history-synthetic-warning'),
            ),
          )
        else
          const Text(
            'Origen de los datos no verificado; el nombre del proveedor '
            'no acredita que sean datos reales.',
            key: Key('persisted-history-unverified-origin'),
          ),
        const Text(
          'Solo lectura. No es una cotización actual ni una señal de inversión. '
          'Licencia, cobertura de 365 días y disponibilidad PIT histórica no acreditadas. '
          'No ejecuta órdenes.',
          key: Key('persisted-history-boundary'),
        ),
        if (!_validSelection)
          const Text('Se requiere un instrumento interno, proveedor y moneda identificados.'),
        OutlinedButton(
          key: const Key('persisted-history-load'),
          onPressed: _validSelection && !_loading ? _refresh : null,
          child: Text(_failed ? 'REINTENTAR HISTÓRICO GUARDADO' : 'CARGAR HISTÓRICO GUARDADO'),
        ),
        if (_loading)
          Semantics(
            liveRegion: true,
            label: 'Cargando histórico guardado.',
            child: const LinearProgressIndicator(),
          ),
        if (_failed)
          Semantics(
            liveRegion: true,
            child: const Text('Histórico guardado no disponible. Puedes reintentar.',
              key: Key('persisted-history-error')),
          ),
        if (history != null) ...[
          Text('Corte de conocimiento: ${history.asOf.toUtc().toIso8601String()}. '
              'Ventana solicitada: últimos 365 días naturales. '
              '${history.points.length} observaciones recuperadas; no acredita sesiones completas.',
              key: const Key('persisted-history-summary')),
          if (history.truncated)
            const Text('Resultado limitado: existen más observaciones que las mostradas.',
              key: Key('persisted-history-truncated')),
          if (history.points.isEmpty)
            Semantics(
              liveRegion: true,
              child: const Text('Sin observaciones guardadas para este instrumento, proveedor y corte.',
                key: Key('persisted-history-empty')),
            ),
          for (final point in history.points)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Text(
                '${point.timestamp.toUtc().toIso8601String()} · '
                'cierre ${point.close!.toStringAsFixed(2)} ${point.currency} · '
                'volumen ${point.volume?.toStringAsFixed(0) ?? "no disponible"}\n'
                'Observación #${point.observationId} · recuperada/disponible localmente '
                '${point.retrievedAt!.toUtc().toIso8601String()} · '
                'fecha de fuente ${point.sourceTimestamp?.toUtc().toIso8601String() ?? "no declarada"}.',
                key: ValueKey('persisted-history-row-${point.observationId}'),
              ),
            ),
        ],
      ],
    );
  }
}
