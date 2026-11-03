import 'package:flutter/material.dart';

import '../../../auth/services/auth_session.dart';
import '../../services/private_research_history_service.dart';

/// Read-only private index; never falls back to public research.
class PrivateResearchHistoryPanel extends StatefulWidget {
  const PrivateResearchHistoryPanel({super.key, required this.symbol, this.service});
  final String symbol;
  final PrivateResearchHistoryService? service;

  @override
  State<PrivateResearchHistoryPanel> createState() => _PrivateResearchHistoryPanelState();
}

class _PrivateResearchHistoryPanelState extends State<PrivateResearchHistoryPanel> {
  PrivateResearchHistoryService? _ownedService;
  Future<PrivateResearchPage>? _pending;
  int _generation = 0;

  PrivateResearchHistoryService get _service =>
      widget.service ?? (_ownedService ??= PrivateResearchHistoryService());

  @override
  void initState() {
    super.initState();
    _reload();
  }

  void _reload() {
    final generation = ++_generation;
    if (!AuthSession.instance.isAuthenticated && widget.service == null) {
      _pending = null;
      return;
    }
    _pending = _service.load(symbol: widget.symbol).then((page) {
      if (generation != _generation) {
        throw StateError('La consulta privada ha quedado obsoleta.');
      }
      return page;
    });
  }

  @override
  void didUpdateWidget(covariant PrivateResearchHistoryPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.symbol != widget.symbol || !identical(oldWidget.service, widget.service)) {
      _ownedService?.dispose();
      _ownedService = null;
      _reload();
    }
  }

  @override
  void dispose() {
    ++_generation;
    _ownedService?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_pending == null) {
      return const Text('Inicia sesión para consultar tus investigaciones privadas.',
          key: Key('private-research-auth-required'));
    }
    return FutureBuilder<PrivateResearchPage>(
      future: _pending,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return Semantics(
            liveRegion: true,
            child: Text('Cargando investigaciones privadas…',
                key: Key('private-research-loading')),
          );
        }
        if (snapshot.hasError || !snapshot.hasData) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('No se puede verificar el historial privado.',
                  key: Key('private-research-error')),
              TextButton(onPressed: () => setState(_reload), child: const Text('Reintentar historial')),
            ],
          );
        }
        final items = snapshot.data!.items;
        if (items.isEmpty) {
          return const Text('No hay investigaciones privadas verificadas para este símbolo.',
              key: Key('private-research-empty'));
        }
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Mis investigaciones persistidas (solo lectura)',
                key: Key('private-research-heading')),
            ...items.map((entry) => ListTile(
              key: Key('private-research-${entry.cycleHash}'),
              title: Text('Corte PIT: ${entry.asOf.toUtc().toIso8601String()}'),
              subtitle: Text('Hash del ciclo: ${entry.cycleHash}'),
            )),
            const Text('El listado no acredita licencias, ejecución de modelos ni autorización de trading.'),
          ],
        );
      },
    );
  }
}
