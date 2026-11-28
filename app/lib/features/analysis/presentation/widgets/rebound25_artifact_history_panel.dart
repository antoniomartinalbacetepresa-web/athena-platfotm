import 'package:flutter/material.dart';

import '../../../auth/services/auth_session.dart';
import '../../services/rebound25_artifact_service.dart';
import '../../services/rebound25_artifact_review_service.dart';
import 'rebound25_artifact_review_form.dart';

/// Separate research records; never adds positions, cash or events to Portfolio.
class Rebound25ArtifactHistoryPanel extends StatefulWidget {
  const Rebound25ArtifactHistoryPanel({
    super.key,
    this.service,
    this.reviewService,
  });
  final Rebound25ArtifactService? service;
  final Rebound25ArtifactReviewService? reviewService;
  @override
  State<Rebound25ArtifactHistoryPanel> createState() =>
      _Rebound25ArtifactHistoryPanelState();
}

class _Rebound25ArtifactHistoryPanelState
    extends State<Rebound25ArtifactHistoryPanel> {
  Rebound25ArtifactService? _owned;
  List<Rebound25ArtifactEntry>? _entries;
  Rebound25Artifact? _detail;
  bool _loading = false;
  bool _failed = false;
  int _generation = 0;
  int _authority = AuthSession.instance.authorityVersion;
  Rebound25ArtifactService get _service =>
      widget.service ?? (_owned ??= Rebound25ArtifactService());
  @override
  void initState() {
    super.initState();
    AuthSession.instance.addListener(_sessionChanged);
  }

  void _clear() {
    ++_generation;
    _entries = null;
    _detail = null;
    _loading = false;
    _failed = false;
  }

  void _sessionChanged() {
    if (_authority == AuthSession.instance.authorityVersion) {
      return;
    }
    _authority = AuthSession.instance.authorityVersion;
    if (mounted) {
      setState(_clear);
    }
  }

  @override
  void didUpdateWidget(covariant Rebound25ArtifactHistoryPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.service != widget.service) {
      _owned?.dispose();
      _owned = null;
      _clear();
    }
  }

  Future<void> _load([String? hash]) async {
    if (_loading || !AuthSession.instance.isAuthenticated) {
      return;
    }
    final generation = _generation;
    setState(() {
      _loading = true;
      _failed = false;
      _detail = null;
      if (hash == null) {
        _entries = null;
      }
    });
    try {
      if (hash == null) {
        final entries = await _service.list();
        if (!mounted || generation != _generation) {
          return;
        }
        setState(() {
          _entries = entries;
          _loading = false;
        });
      } else {
        final detail = await _service.get(hash);
        if (!mounted || generation != _generation) {
          return;
        }
        setState(() {
          _detail = detail;
          _loading = false;
        });
      }
    } catch (_) {
      if (!mounted || generation != _generation) {
        return;
      }
      setState(() {
        _failed = true;
        _loading = false;
      });
    }
  }

  @override
  void dispose() {
    ++_generation;
    AuthSession.instance.removeListener(_sessionChanged);
    _owned?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      const Text(
        'Simulaciones guardadas — investigación privada',
        key: Key('rebound25-artifact-history-heading'),
      ),
      const Text(
        'DATOS ARTIFICIALES. Vista de lectura separada de tus posiciones, capital y saldo. '
        'Un backtest no acredita rentabilidad, datos reales ni órdenes ejecutadas.',
      ),
      if (!AuthSession.instance.isAuthenticated)
        const Text(
          'Inicia sesión para consultar tus simulaciones.',
          key: Key('rebound25-artifact-auth-required'),
        )
      else ...[
        TextButton(
          key: const Key('rebound25-artifact-history-load'),
          onPressed: _loading ? null : () => _load(),
          child: const Text('CARGAR MIS SIMULACIONES'),
        ),
        if (_loading)
          const LinearProgressIndicator(key: Key('rebound25-artifact-loading')),
        if (_failed)
          const Text(
            'No se pudo verificar la simulación privada. Reintenta la consulta.',
            key: Key('rebound25-artifact-error'),
          ),
        if (_entries != null && _entries!.isEmpty)
          const Text(
            'No hay simulaciones guardadas para esta cuenta.',
            key: Key('rebound25-artifact-empty'),
          ),
        if (_entries != null)
          const Text('Se muestran hasta 20 simulaciones recientes.'),
        if (_entries != null)
          for (final entry in _entries!)
            TextButton(
              key: ValueKey('rebound25-artifact-open-${entry.artifactHash}'),
              onPressed: _loading ? null : () => _load(entry.artifactHash),
              child: Text(
                'ABRIR ${entry.artifactHash.substring(0, 12)} · Guardado ${entry.createdAt.toIso8601String()}',
              ),
            ),
        if (_detail != null) ...[
          Text(
            'Artefacto privado verificado: ${_detail!.artifactHash}',
            key: const Key('rebound25-artifact-detail'),
          ),
          Text(
            'Disponible como investigación desde ${_detail!.createdAt.toIso8601String()}; '
            'no existía en el corte de la serie artificial de febrero de 2026.',
          ),
          Text(
            '${_detail!.result.tradeCount} operaciones simuladas cerradas · '
            'PnL simulado ${_detail!.result.totalNetPnl.toStringAsFixed(2)} ${_detail!.result.currency}',
          ),
          Text(
            'Benchmark de liquidación hipotética: ${_detail!.result.benchmarkHypotheticalPnl.toStringAsFixed(2)} '
            '${_detail!.result.currency}. Capital y exposición no normalizados.',
          ),
          SelectableText(
            'Huella del resultado: ${_detail!.result.resultFingerprint}',
          ),
          Rebound25ArtifactReviewForm(
            key: ValueKey(_detail!.artifactHash),
            artifact: _detail!,
            service: widget.reviewService,
          ),
        ],
      ],
    ],
  );
}
