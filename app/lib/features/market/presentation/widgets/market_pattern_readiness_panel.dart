import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

/// Displays the backend's *unverified* historical coverage without implying
/// licensed data, a historical PIT snapshot, or actionable entry/exit signals.
class MarketPatternReadinessPanel extends StatefulWidget {
  const MarketPatternReadinessPanel({
    super.key,
    required this.symbol,
    this.load,
  });

  final String symbol;
  final Future<Map<String, dynamic>> Function(String symbol)? load;

  @override
  State<MarketPatternReadinessPanel> createState() =>
      _MarketPatternReadinessPanelState();
}

class _MarketPatternReadinessPanelState
    extends State<MarketPatternReadinessPanel> {
  static const _backend = String.fromEnvironment(
    'ATHENA_BACKEND_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );

  int _generation = 0;
  bool _loading = false;
  bool _error = false;
  Map<String, dynamic>? _report;

  @override
  void didUpdateWidget(covariant MarketPatternReadinessPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.symbol != widget.symbol || oldWidget.load != widget.load) {
      _generation++;
      _report = null;
      _error = false;
      _loading = false;
    }
  }

  @override
  void dispose() {
    _generation++;
    super.dispose();
  }

  Future<Map<String, dynamic>> _fetch(String symbol) async {
    final client = http.Client();
    try {
      final uri = Uri.parse('$_backend/api/v1/market/opportunity-pattern-readiness')
          .replace(queryParameters: {'symbol': symbol});
      final response = await client.get(uri).timeout(const Duration(seconds: 15));
      if (response.statusCode != 200) throw const FormatException('HTTP error');
      final decoded = jsonDecode(response.body);
      if (decoded is! Map || decoded['data'] is! Map) {
        throw const FormatException('Invalid response');
      }
      return Map<String, dynamic>.from(decoded['data'] as Map);
    } finally {
      client.close();
    }
  }

  Future<void> _refresh() async {
    final symbol = widget.symbol.trim().toUpperCase();
    if (symbol.isEmpty) return;
    final generation = ++_generation;
    setState(() {
      _loading = true;
      _error = false;
      _report = null;
    });
    try {
      final report = await (widget.load ?? _fetch)(symbol);
      if (!mounted || generation != _generation) return;
      if (report['symbol'] != symbol ||
          report['status'] != 'blocked_unverified_market_evidence' ||
          report['licenceVerified'] != false ||
          report['historicalPointInTimeEligible'] != false ||
          report['patternComputed'] != false ||
          report['automaticTrading'] != false) {
        throw const FormatException('Unexpected evidence contract');
      }
      // A malformed provider payload must not crash Flutter's build phase or
      // display fabricated coverage. Keep this diagnostic fail-closed.
      final sessions = report['validDailySessions'];
      final discarded = report['invalidOrDuplicateRows'];
      final age = report['latestObservationAgeCalendarDays'];
      final providers = report['sourceProviders'];
      final checkedAt = report['checkedAt'];
      if (sessions is! int || sessions < 0 ||
          discarded is! int || discarded < 0 ||
          (age != null && (age is! int || age < 0)) ||
          providers is! List ||
          providers.any((value) => value is! String || value.trim().isEmpty) ||
          checkedAt is! String ||
          DateTime.tryParse(checkedAt) == null ||
          (report['firstObservedDate'] != null &&
              report['firstObservedDate'] is! String) ||
          (report['lastObservedDate'] != null &&
              report['lastObservedDate'] is! String)) {
        throw const FormatException('Malformed historical coverage');
      }
      setState(() {
        _report = report;
        _loading = false;
      });
    } catch (_) {
      if (!mounted || generation != _generation) return;
      setState(() {
        _error = true;
        _loading = false;
        _report = null;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final report = _report;
    return Semantics(
      container: true,
      label: 'Diagnóstico informativo del histórico bursátil. No es una señal de inversión.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          OutlinedButton(
            key: const Key('market-pattern-readiness-request'),
            onPressed: _loading ? null : _refresh,
            child: const Text('COMPROBAR HISTÓRICO PARA PATRONES'),
          ),
          if (_loading) const LinearProgressIndicator(),
          if (_error)
            const Text(
              'No se pudo comprobar el histórico. Reintentar más tarde.',
              key: Key('market-pattern-readiness-error'),
            ),
          if (report != null) ...[
            Text(
              'Histórico de ${report['symbol']}: ${report['validDailySessions']} '
              'observaciones diarias; ${report['invalidOrDuplicateRows']} '
              'registros descartados.',
              key: const Key('market-pattern-readiness-coverage'),
            ),
            Text(
              'Primera observación: ${report['firstObservedDate'] ?? 'sin datos'}; '
              'última: ${report['lastObservedDate'] ?? 'sin datos'}. '
              'Antigüedad: ${report['latestObservationAgeCalendarDays'] ?? 'desconocida'} '
              'días naturales. Comprobado: ${report['checkedAt']}.',
              key: const Key('market-pattern-readiness-time'),
            ),
            Text(
              'Proveedor declarado: ${(report['sourceProviders'] as List?)?.join(', ') ?? 'desconocido'}. '
              'Cobertura 365 días y calendario bursátil: NO VERIFICADOS.',
              key: const Key('market-pattern-readiness-source'),
            ),
            const Text(
              'BLOQUEADO: licencia, ajustes por splits/dividendos y evidencia PIT '
              'histórica no acreditados. No se calculan patrones ni señales '
              'de compra o venta. Investigación de solo lectura.',
              key: Key('market-pattern-readiness-blocked'),
            ),
          ],
        ],
      ),
    );
  }
}
