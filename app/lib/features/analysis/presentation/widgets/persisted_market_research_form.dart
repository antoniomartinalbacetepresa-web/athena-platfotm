import 'package:flutter/material.dart';

import '../../../auth/services/auth_session.dart';
import '../../../market/models/market_quote.dart';
import '../../../market/data/models/persisted_market_history.dart';
import '../../services/persisted_market_research_service.dart';
import '../../services/private_research_history_service.dart';
import 'private_research_history_panel.dart';

/// Explicit human review of synthetic research. Does not submit on opening.
class PersistedMarketResearchForm extends StatefulWidget {
  const PersistedMarketResearchForm({
    super.key,
    required this.quote,
    required this.history,
    this.service,
    this.historyService,
  });
  final MarketQuote quote;
  final PersistedMarketHistory history;
  final PersistedMarketResearchService? service;
  final PrivateResearchHistoryService? historyService;

  @override
  State<PersistedMarketResearchForm> createState() =>
      _PersistedMarketResearchFormState();
}

class _PersistedMarketResearchFormState
    extends State<PersistedMarketResearchForm> {
  final _thesis = TextEditingController();
  final _objection = TextEditingController();
  final _sources = TextEditingController();
  PersistedMarketResearchService? _owned;
  PersistedMarketResearchDraft? _draft;
  PrivateResearchCycleDetail? _result;
  bool _reviewed = false;
  bool _busy = false;
  bool _failed = false;
  bool _validationFailed = false;
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
    if (mounted) setState(_reset);
  }

  void _reset() {
    ++_generation;
    _draft = null;
    _result = null;
    _reviewed = false;
    _busy = false;
    _failed = false;
    _validationFailed = false;
    _thesis.clear();
    _objection.clear();
    _sources.clear();
  }

  @override
  void didUpdateWidget(covariant PersistedMarketResearchForm oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.quote.instrumentId != widget.quote.instrumentId ||
        oldWidget.quote.symbol != widget.quote.symbol ||
        oldWidget.quote.sourceProvider != widget.quote.sourceProvider ||
        oldWidget.history.asOf != widget.history.asOf ||
        oldWidget.service != widget.service) {
      _reset();
    }
  }

  Future<void> _submit() async {
    if (_busy || _result != null || !AuthSession.instance.isAuthenticated) {
      return;
    }
    final sources = _sources.text
        .trim()
        .split(RegExp(r'[\s,]+'))
        .where((hash) => hash.isNotEmpty)
        .toList();
    if (sources.length > 5 ||
        sources.any((hash) => !RegExp(r'^[a-f0-9]{64}$').hasMatch(hash)) ||
        !_reviewed ||
        _thesis.text.trim().isEmpty ||
        _objection.text.trim().isEmpty) {
      setState(() {
        _validationFailed = true;
      });
      return;
    }
    _validationFailed = false;
    final generation = _generation;
    setState(() {
      _busy = true;
      _failed = false;
    });
    try {
      // Human context becomes available NOW; never backdate it to the old history cutoff.
      final authoredAt = DateTime.now().toUtc();
      final draft = _draft ??= PersistedMarketResearchDraft(
        instrumentId: widget.quote.instrumentId!,
        symbol: widget.quote.symbol,
        sourceProvider: widget.quote.sourceProvider!,
        observedFrom: widget.history.asOf.subtract(const Duration(days: 365)),
        observedTo: widget.history.asOf,
        authoredAt: authoredAt,
        journalId:
            'market-${widget.quote.instrumentId}-${authoredAt.microsecondsSinceEpoch}',
        thesis: _thesis.text,
        contradiction: _objection.text,
        sourceCycleHashes: sources,
      );
      final service =
          widget.service ?? (_owned ??= PersistedMarketResearchService());
      final result = await service.create(draft);
      if (!mounted || generation != _generation) return;
      setState(() {
        _result = result;
        _busy = false;
      });
    } catch (_) {
      if (!mounted || generation != _generation) return;
      setState(() {
        _failed = true;
        _busy = false;
      });
    }
  }

  @override
  void dispose() {
    ++_generation;
    AuthSession.instance.removeListener(_sessionChanged);
    _owned?.dispose();
    _thesis.dispose();
    _objection.dispose();
    _sources.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!widget.history.containsSyntheticEvidence ||
        widget.history.points.isEmpty) {
      return const SizedBox.shrink();
    }
    if (!AuthSession.instance.isAuthenticated) {
      return const Text(
        'Inicia sesión para crear una investigación privada con estos fixtures.',
        key: Key('market-cycle-auth-required'),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Investigación privada con datos sintéticos',
          key: Key('market-cycle-heading'),
        ),
        const Text(
          'El servidor selecciona hasta 200 observaciones de esta ventana. '
          'Pueden aparecer filas recuperadas después de la vista previa; revisa la referencia resultante. '
          'El contexto humano se fecha al enviarlo; no acredita PIT histórico ni genera órdenes.',
        ),
        TextField(
          controller: _thesis,
          enabled: !_busy && _draft == null,
          key: const Key('market-cycle-thesis'),
          maxLength: 4000,
          decoration: const InputDecoration(
            labelText: 'Pregunta o hipótesis de investigación',
          ),
        ),
        TextField(
          controller: _objection,
          enabled: !_busy && _draft == null,
          key: const Key('market-cycle-objection'),
          maxLength: 4000,
          decoration: const InputDecoration(
            labelText: 'Objeción o explicación alternativa',
          ),
        ),
        TextField(
          controller: _sources,
          enabled: !_busy && _draft == null,
          key: const Key('market-cycle-sources'),
          maxLength: 400,
          decoration: const InputDecoration(
            labelText: 'Hashes de ciclos News/Investors privados (opcional)',
            helperText: 'Hasta 5 hashes del historial, separados por espacios o comas. El servidor verifica propietario, instrumento y fechas.',
          ),
        ),
        CheckboxListTile(
          key: const Key('market-cycle-review'),
          title: const Text(
            'He revisado el contexto y sus límites sintéticos. No es una orden.',
          ),
          value: _reviewed,
          onChanged: _busy || _draft != null
              ? null
              : (value) => setState(() {
                  _reviewed = value ?? false;
                }),
        ),
        FilledButton(
          key: const Key('market-cycle-submit'),
          onPressed: _busy || _result != null ? null : _submit,
          child: Text(
            _failed
                ? 'REINTENTAR MISMA SOLICITUD'
                : 'CREAR INVESTIGACIÓN PRIVADA',
          ),
        ),
        if (_busy)
          const LinearProgressIndicator(key: Key('market-cycle-loading')),
        if (_validationFailed)
          const Text(
            'Revisa hipótesis, objeción, confirmación y hashes opcionales.',
            key: Key('market-cycle-validation'),
          ),
        if (_failed)
          const Text(
            'No se pudo verificar el resultado. Reintenta la misma solicitud; '
            'el servidor puede haberla guardado y el reintento no crea otra revisión.',
            key: Key('market-cycle-error'),
          ),
        if (_result != null) ...[
          SelectableText(
            'Ciclo privado recuperado: ${_result!.cycleHash}\n'
            'Corte: ${_result!.asOf.toIso8601String()}. '
            'Revisa las evidencias antes de extraer conclusiones.',
            key: const Key('market-cycle-result'),
          ),
          PrivateResearchHistoryPanel(
            key: ValueKey(_result!.cycleHash),
            symbol: widget.quote.symbol,
            service: widget.historyService,
          ),
        ],
      ],
    );
  }
}
