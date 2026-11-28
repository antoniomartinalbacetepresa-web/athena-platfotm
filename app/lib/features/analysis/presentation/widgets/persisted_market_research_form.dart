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
  PrivateResearchHistoryService? _ownedReader;
  List<PrivateResearchEntry>? _sourceOptions;
  bool _sourceBusy = false;
  bool _sourceError = false;
  PersistedMarketResearchDraft? _draft;
  PrivateResearchCycleDetail? _result;
  bool _reviewed = false;
  bool _busy = false;
  bool _failed = false;
  bool _rejected = false;
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
    _sourceOptions = null;
    _sourceBusy = false;
    _sourceError = false;
    _draft = null;
    _result = null;
    _reviewed = false;
    _busy = false;
    _failed = false;
    _rejected = false;
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
        oldWidget.service != widget.service ||
        oldWidget.historyService != widget.historyService) {
      _reset();
    }
  }

  Future<void> _loadSources() async {
    if (_sourceBusy ||
        _busy ||
        _draft != null ||
        !AuthSession.instance.isAuthenticated) {
      return;
    }
    final generation = _generation;
    setState(() {
      _sourceBusy = true;
      _sourceError = false;
      _sourceOptions = null;
    });
    try {
      final reader =
          widget.historyService ??
          (_ownedReader ??= PrivateResearchHistoryService());
      final page = await reader.load(symbol: widget.quote.symbol);
      if (!mounted || generation != _generation) return;
      setState(() {
        _sourceOptions = List.unmodifiable(page.items);
        _sourceBusy = false;
      });
    } catch (_) {
      if (!mounted || generation != _generation) return;
      setState(() {
        _sourceError = true;
        _sourceBusy = false;
      });
    }
  }

  void _useSource(String hash) {
    if (_busy || _draft != null) return;
    final values = _sources.text
        .trim()
        .split(RegExp(r'[\s,]+'))
        .where((value) => value.isNotEmpty)
        .toSet();
    values.add(hash);
    if (values.length > 5) {
      setState(() {
        _validationFailed = true;
      });
      return;
    }
    setState(() {
      _sources.text = (values.toList()..sort()).join(', ');
    });
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
    } on PersistedMarketResearchRejected {
      if (!mounted || generation != _generation) return;
      setState(() {
        _rejected = true;
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
    _ownedReader?.dispose();
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
        TextButton(
          key: const Key('market-cycle-load-sources'),
          onPressed: _busy || _draft != null || _sourceBusy
              ? null
              : _loadSources,
          child: const Text('MOSTRAR MIS CICLOS PARA ESTE SÍMBOLO'),
        ),
        if (_sourceBusy)
          const LinearProgressIndicator(
            key: Key('market-cycle-sources-loading'),
          ),
        if (_sourceError)
          const Text(
            'No se pudo consultar el historial privado. Puedes reintentar.',
            key: Key('market-cycle-sources-error'),
          ),
        if (_sourceOptions != null) ...[
          const Text(
            'Ciclos candidatos: la lista no acredita que contengan News/Investors ni el mismo listing. El servidor lo verificará.',
          ),
          if (_sourceOptions!.isEmpty)
            const Text('No hay ciclos privados para este símbolo.'),
          for (final entry in _sourceOptions!)
            TextButton(
              key: ValueKey('market-cycle-use-source-${entry.cycleHash}'),
              onPressed: _busy || _draft != null
                  ? null
                  : () => _useSource(entry.cycleHash),
              child: Text(
                'USAR ${entry.cycleHash.substring(0, 12)} · ${entry.asOf.toIso8601String()}',
              ),
            ),
        ],
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
          onPressed: _busy || _result != null || _rejected ? null : _submit,
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
        if (_rejected) ...[
          const Text(
            'El servidor rechazó esta solicitud. Consulta el historial antes de crear otra revisión; '
            'puede existir un resultado de un intento anterior.',
            key: Key('market-cycle-rejected'),
          ),
          TextButton(
            key: const Key('market-cycle-correct-draft'),
            onPressed: () => setState(() {
              ++_generation;
              _draft = null;
              _rejected = false;
              _failed = false;
              _reviewed = false;
              _validationFailed = false;
            }),
            child: const Text('CORREGIR Y VOLVER A REVISAR'),
          ),
        ],
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
