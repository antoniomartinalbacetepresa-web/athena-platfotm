import 'package:flutter/material.dart';

import '../../../auth/services/auth_session.dart';
import '../../services/rebound25_research_service.dart';
import '../../services/rebound25_artifact_service.dart';
import 'rebound25_artifact_history_panel.dart';

/// An explicit artificial laboratory; never adapts live quotes into backtests.
class Rebound25ResearchPanel extends StatefulWidget {
  const Rebound25ResearchPanel({super.key, this.service, this.artifactService});
  final Rebound25ResearchService? service;
  final Rebound25ArtifactService? artifactService;
  @override
  State<Rebound25ResearchPanel> createState() => _Rebound25ResearchPanelState();
}

class _Rebound25ResearchPanelState extends State<Rebound25ResearchPanel> {
  final _target = TextEditingController(text: '2');
  final _stop = TextEditingController(text: '1');
  final _holding = TextEditingController(text: '5');
  final _commission = TextEditingController(text: '1');
  final _spread = TextEditingController(text: '10');
  final _slippage = TextEditingController(text: '5');
  Rebound25ResearchService? _owned;
  Rebound25ArtifactService? _ownedArtifacts;
  Rebound25Artifact? _saved;
  bool _saving = false;
  bool _saveFailed = false;
  Rebound25ResearchResult? _result;
  Map<String, dynamic>? _request;
  bool _busy = false;
  String? _error;
  int _generation = 0;
  int _authority = AuthSession.instance.authorityVersion;
  @override
  void initState() {
    super.initState();
    AuthSession.instance.addListener(_sessionChanged);
  }

  void _sessionChanged() {
    if (_authority == AuthSession.instance.authorityVersion) return;
    _authority = AuthSession.instance.authorityVersion;
    if (mounted) {
      setState(() {
        _clear();
        for (final pair in [
          (_target, '2'),
          (_stop, '1'),
          (_holding, '5'),
          (_commission, '1'),
          (_spread, '10'),
          (_slippage, '5'),
        ]) {
          pair.$1.text = pair.$2;
        }
      });
    }
  }

  void _clear() {
    ++_generation;
    _saved = null;
    _saving = false;
    _saveFailed = false;
    _request = null;
    _result = null;
    _error = null;
    _busy = false;
  }

  double _number(TextEditingController field) {
    final value = double.tryParse(field.text.trim().replaceAll(',', '.'));
    if (value == null || !value.isFinite || value < 0) {
      throw const FormatException();
    }
    return value;
  }

  Map<String, dynamic> _fixture() {
    final target = _number(_target), stop = _number(_stop);
    final holding = int.tryParse(_holding.text.trim());
    final commission = _number(_commission),
        spread = _number(_spread),
        slippage = _number(_slippage);
    if (target <= 0 ||
        stop <= 0 ||
        stop >= 100 ||
        holding == null ||
        holding < 1 ||
        holding > 252 ||
        spread / 2 + slippage >= 10000) {
      throw const FormatException();
    }
    final start = DateTime.utc(2026, 1, 1);
    final bars = <Map<String, dynamic>>[];
    final sessions = <String>[];
    for (var index = 0; index < 40; index++) {
      final day = start.add(Duration(days: index));
      final session = day.toIso8601String().substring(0, 10);
      sessions.add(session);
      final open = index == 25
          ? 98.0
          : index == 26
          ? 95.0
          : index == 27
          ? 97.0
          : 100.0;
      final close = index == 25
          ? 95.0
          : index == 26
          ? 97.0
          : index == 27
          ? 99.0
          : 100.0;
      bars.add({
        'session': session,
        'openAt': day.add(const Duration(hours: 9)).toIso8601String(),
        'observedAt': day.add(const Duration(hours: 17)).toIso8601String(),
        'availableAt': day.add(const Duration(hours: 18)).toIso8601String(),
        'open': open,
        'high': index == 25
            ? 99.0
            : index == 26
            ? 98.0
            : index == 27
            ? 100.0
            : 102.0,
        'low': index == 25 || index == 26
            ? 94.0
            : index == 27
            ? 96.0
            : 99.0,
        'close': close,
        'volume': index == 25 || index == 26 ? 2000.0 : 1000.0,
      });
    }
    return {
      'evidenceKind': 'synthetic_fixture',
      'instrumentId': 'SYNTHETIC-LAB-25',
      'currency': 'USD',
      'asOf': bars.last['availableAt'],
      'precommittedAt': start
          .add(const Duration(days: 25, hours: 8))
          .toIso8601String(),
      'expectedSessions': sessions,
      'bars': bars,
      'parameters': {
        'takeProfitPct': target,
        'stopLossPct': stop,
        'maxHoldingSessions': holding,
        'commissionBps': commission,
        'spreadBps': spread,
        'slippageBps': slippage,
        'orderUnits': 1.0,
        'minAverageVolume': 1.0,
        'maxVolumeParticipation': 0.01,
        'minRelativeVolume': 0.0,
        'lookbackSessions': 25,
        'minReboundPct': 1.0,
        'maxConfirmationSessions': 3,
        'version': 'rebound25-synthetic-v1',
      },
    };
  }

  Future<void> _run() async {
    if (_busy || !AuthSession.instance.isAuthenticated) return;
    final generation = _generation;
    try {
      final request = _request ??= _fixture();
      setState(() {
        _busy = true;
        _error = null;
        _result = null;
      });
      final service = widget.service ?? (_owned ??= Rebound25ResearchService());
      final result = await service.run(request);
      if (!mounted || generation != _generation) return;
      setState(() {
        _result = result;
        _busy = false;
      });
    } on FormatException {
      if (mounted && generation == _generation) {
        setState(() {
          _busy = false;
          _error = 'Parámetros o respuesta no válidos.';
        });
      }
    } catch (_) {
      if (mounted && generation == _generation) {
        setState(() {
          _busy = false;
          _error = 'Simulación no disponible. Puedes reintentar.';
        });
      }
    }
  }

  Future<void> _save() async {
    final request = _request, result = _result;
    if (_saving ||
        _saved != null ||
        request == null ||
        result == null ||
        !AuthSession.instance.isAuthenticated) {
      return;
    }
    final generation = _generation;
    setState(() {
      _saving = true;
      _saveFailed = false;
    });
    try {
      final service =
          widget.artifactService ??
          (_ownedArtifacts ??= Rebound25ArtifactService());
      final artifact = await service.save(
        request,
        expectedResultFingerprint: result.resultFingerprint,
      );
      if (!mounted || generation != _generation) return;
      setState(() {
        _saved = artifact;
        _saving = false;
      });
    } catch (_) {
      if (!mounted || generation != _generation) return;
      setState(() {
        _saveFailed = true;
        _saving = false;
      });
    }
  }

  @override
  void didUpdateWidget(covariant Rebound25ResearchPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.service != widget.service ||
        oldWidget.artifactService != widget.artifactService) {
      _owned?.dispose();
      _owned = null;
      _ownedArtifacts?.dispose();
      _ownedArtifacts = null;
      _clear();
    }
  }

  @override
  void dispose() {
    ++_generation;
    AuthSession.instance.removeListener(_sessionChanged);
    _owned?.dispose();
    _ownedArtifacts?.dispose();
    for (final controller in [
      _target,
      _stop,
      _holding,
      _commission,
      _spread,
      _slippage,
    ]) {
      controller.dispose();
    }
    super.dispose();
  }

  Widget _input(String label, String key, TextEditingController controller) =>
      TextField(
        key: Key(key),
        controller: controller,
        enabled: !_busy && _request == null,
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        decoration: InputDecoration(labelText: label),
      );
  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      const Text(
        'Laboratorio de rebote de 25 sesiones',
        key: Key('rebound25-heading'),
      ),
      const Text(
        'DATOS ARTIFICIALES. Plantilla de 40 sesiones consecutivas, no calendario bursátil real. '
        'Incluye una barra ambigua para comprobar el stop conservador. No usa cotizaciones de Market. '
        'Parámetros ilustrativos, no límites aprobados para invertir. Solo se guarda al solicitarlo; no ejecuta órdenes.',
        key: Key('rebound25-synthetic-warning'),
      ),
      if (!AuthSession.instance.isAuthenticated)
        const Text(
          'Inicia sesión para ejecutar la simulación.',
          key: Key('rebound25-auth-required'),
        )
      else ...[
        _input('Objetivo (%)', 'rebound25-target', _target),
        _input('Stop (%)', 'rebound25-stop', _stop),
        _input('Máximo de sesiones', 'rebound25-holding', _holding),
        _input('Comisión por lado (bps)', 'rebound25-commission', _commission),
        _input('Spread completo (bps)', 'rebound25-spread', _spread),
        _input('Deslizamiento por lado (bps)', 'rebound25-slippage', _slippage),
        const Text(
          'Una unidad; confirmación >1%, espera máxima 3 sesiones. '
          'Participación máxima ilustrativa 1%; RVOL mínimo 0. Calendario y precommit declarados, no atestados.',
        ),
        FilledButton(
          key: const Key('rebound25-run'),
          onPressed: _busy || _saving ? null : _run,
          child: const Text('SIMULAR FIXTURES'),
        ),
        if (_busy) const LinearProgressIndicator(key: Key('rebound25-loading')),
        if (_error != null) Text(_error!, key: const Key('rebound25-error')),
        if (_request != null && !_busy && !_saving)
          TextButton(
            onPressed: () => setState(_clear),
            child: const Text('NUEVOS PARÁMETROS'),
          ),
        if (_result != null) ...[
          Text(
            '${_result!.tradeCount} operaciones cerradas · PnL simulado ${_result!.totalNetPnl.toStringAsFixed(2)} USD',
            key: const Key('rebound25-result'),
          ),
          Text(
            'Benchmark: liquidación hipotética ${_result!.benchmarkHypotheticalPnl.toStringAsFixed(2)} USD. '
            'Capital y exposición no normalizados; no demuestra superioridad ni rentabilidad futura.',
          ),
          SelectableText(
            'Parámetros: ${_result!.parametersFingerprint}\nResultado: ${_result!.resultFingerprint}',
          ),
          for (final warning in _result!.warnings) Text(warning),
          FilledButton(
            key: const Key('rebound25-artifact-save'),
            onPressed: _saving || _saved != null ? null : _save,
            child: Text(
              _saveFailed
                  ? 'REINTENTAR MISMO GUARDADO'
                  : 'GUARDAR SIMULACIÓN PRIVADA',
            ),
          ),
          if (_saving)
            const LinearProgressIndicator(
              key: Key('rebound25-artifact-saving'),
            ),
          if (_saveFailed)
            const Text(
              'No se pudo verificar el guardado. El servidor puede haberlo conservado; '
              'reintenta los mismos parámetros sin duplicar el artefacto.',
              key: Key('rebound25-artifact-save-error'),
            ),
          if (_saved != null) ...[
            SelectableText(
              'Guardado y recuperado: ${_saved!.artifactHash} · '
              'Disponible desde ${_saved!.createdAt.toIso8601String()}',
              key: const Key('rebound25-artifact-saved'),
            ),
            Rebound25ArtifactHistoryPanel(
              key: ValueKey(_saved!.artifactHash),
              service: widget.artifactService ?? _ownedArtifacts,
            ),
          ],
        ],
      ],
    ],
  );
}
