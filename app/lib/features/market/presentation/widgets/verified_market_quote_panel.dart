import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../di/market_dependencies.dart';
import '../../models/market_quote.dart';
import '../../repositories/market_repository.dart';

/// Read-only quote preview. Provenance is declared by the backend, not
/// independently attested; missing or contradictory evidence fails closed.
class VerifiedMarketQuotePanel extends StatefulWidget {
  final String symbol;
  final MarketRepository? repository;

  const VerifiedMarketQuotePanel({super.key, required this.symbol, this.repository});

  @override
  State<VerifiedMarketQuotePanel> createState() => _VerifiedMarketQuotePanelState();
}

class _VerifiedMarketQuotePanelState extends State<VerifiedMarketQuotePanel> {
  MarketDependencies? _dependencies;
  MarketQuote? _quote;
  bool _loading = false;
  bool _failed = false;
  int _generation = 0;

  @override
  void didUpdateWidget(covariant VerifiedMarketQuotePanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.symbol.trim().toUpperCase() != widget.symbol.trim().toUpperCase() ||
        !identical(oldWidget.repository, widget.repository)) {
      _generation++;
      _quote = null;
      _loading = false;
      _failed = false;
    }
  }

  @override
  void dispose() {
    _generation++;
    _dependencies?.dispose();
    super.dispose();
  }

  void _request() {
    final symbol = widget.symbol.trim().toUpperCase();
    if (symbol.isEmpty) return;
    final generation = ++_generation;
    setState(() {
      _quote = null;
      _loading = true;
      _failed = false;
    });
    _fetch(symbol, generation);
  }

  Future<void> _fetch(String symbol, int generation) async {
    try {
      final repository = widget.repository ??
          (_dependencies ??= MarketDependencies.create()).repository;
      final quote = await repository.getQuote(symbol).timeout(const Duration(seconds: 15));
      if (!mounted || generation != _generation) return;
      if (!_traceable(quote, symbol)) {
        throw const FormatException('Cotización sin identidad y procedencia válidas.');
      }
      setState(() {
        _quote = quote;
        _loading = false;
        _failed = false;
      });
    } catch (_) {
      if (!mounted || generation != _generation) return;
      // Never display provider errors: their text may contain credentials.
      setState(() {
        _quote = null;
        _loading = false;
        _failed = true;
      });
    }
  }

  bool _traceable(MarketQuote quote, String requested) {
    final now = DateTime.now().toUtc();
    final retrieved = quote.retrievedAt?.toUtc();
    final observed = quote.updatedAt.toUtc();
    return quote.symbol.trim().toUpperCase() == requested &&
        quote.currentPrice.isFinite && quote.currentPrice > 0 &&
        quote.sourceProvider != null && quote.sourceProvider!.trim().isNotEmpty &&
        retrieved != null &&
        !retrieved.isAfter(now.add(const Duration(minutes: 5))) &&
        !observed.isAfter(now.add(const Duration(minutes: 5))) &&
        !observed.isAfter(retrieved.add(const Duration(minutes: 5)));
  }

  @override
  Widget build(BuildContext context) {
    final symbol = widget.symbol.trim().toUpperCase();
    final quote = _quote;
    final historical = quote != null &&
        (DateTime.now().toUtc().difference(quote.updatedAt.toUtc()) > const Duration(hours: 24) ||
         DateTime.now().toUtc().difference(quote.retrievedAt!.toUtc()) > const Duration(hours: 24));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Align(
          alignment: Alignment.centerLeft,
          child: OutlinedButton(
            key: const Key('market-quote-request'),
            onPressed: symbol.isEmpty ? null : _request,
            child: const Text('CONSULTAR COTIZACIÓN'),
          ),
        ),
        if (_loading)
          const Semantics(
            liveRegion: true,
            label: 'Consultando cotización y procedencia.',
            child: LinearProgressIndicator(),
          ),
        if (_failed)
          const Semantics(
            liveRegion: true,
            child: Text(
              'COTIZACIÓN NO VERIFICABLE. Reintentar o consultar otra empresa.',
              key: Key('market-quote-error'),
              style: TextStyle(color: AthenaColors.danger),
            ),
          ),
        if (quote != null) ...[
          Text(
            '${quote.symbol} · ${quote.currentPrice.toStringAsFixed(2)} ${quote.currency ?? "(moneda no declarada)"}',
            key: const Key('market-quote-price'),
            style: const TextStyle(color: AthenaColors.text),
          ),
          Text(
            'Fuente declarada: ${quote.sourceProvider} · ${quote.exchange ?? "mercado no declarado"}',
            key: const Key('market-quote-source'),
            style: const TextStyle(color: AthenaColors.textSecondary, fontSize: 11),
          ),
          Text(
            'Observada: ${quote.updatedAt.toUtc().toIso8601String()} · '
            'recuperada: ${quote.retrievedAt!.toUtc().toIso8601String()}',
            key: const Key('market-quote-timestamps'),
            style: const TextStyle(color: AthenaColors.textSecondary, fontSize: 10),
          ),
          if (historical)
            const Semantics(
              liveRegion: true,
              child: Text(
                'COTIZACIÓN HISTÓRICA: observación o recuperación de más de 24 horas; no es un precio en tiempo real.',
                key: Key('market-quote-stale'),
                style: TextStyle(color: Color(0xFFFFD37A), fontSize: 11),
              ),
            ),
        ],
      ],
    );
  }
}
