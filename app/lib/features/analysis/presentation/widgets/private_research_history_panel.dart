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
  Future<PrivateResearchCycleDetail>? _selectedDetail;
  int _sessionVersion = AuthSession.instance.authorityVersion;

  PrivateResearchHistoryService get _service =>
      widget.service ?? (_ownedService ??= PrivateResearchHistoryService());

  @override
  void initState() {
    super.initState();
    AuthSession.instance.addListener(_onSessionChanged);
    _reload();
  }

  void _onSessionChanged() {
    if (!mounted) return;
    final nextVersion = AuthSession.instance.authorityVersion;
    if (nextVersion == _sessionVersion) return;
    _sessionVersion = nextVersion;
    setState(_reload);
  }

  void _reload() {
    final generation = ++_generation;
    _selectedDetail = null;
    if (!AuthSession.instance.isAuthenticated) {
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

  void _openCycle(PrivateResearchEntry entry) {
    if (!AuthSession.instance.isAuthenticated) return;
    final generation = _generation;
    setState(() {
      _selectedDetail = _service.loadCycle(entry).then((detail) {
        if (generation != _generation || !AuthSession.instance.isAuthenticated) {
          throw StateError('La consulta privada ha quedado obsoleta.');
        }
        return detail;
      });
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

  String _pitAge(DateTime asOf) {
    final age = DateTime.now().toUtc().difference(asOf.toUtc());
    if (age.isNegative) return 'fecha futura no verificada';
    if (age.inDays > 0) return '${age.inDays} días';
    if (age.inHours > 0) return '${age.inHours} horas';
    return '${age.inMinutes} minutos';
  }

  @override
  void dispose() {
    ++_generation;
    AuthSession.instance.removeListener(_onSessionChanged);
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
              subtitle: Text('Hash del ciclo: ${entry.cycleHash}\n'
                  'Antigüedad del corte PIT: ${_pitAge(entry.asOf)}. '
                  'La fecha PIT no acredita actualidad de precios ni noticias.'),
              trailing: TextButton(
                onPressed: () => _openCycle(entry),
                child: const Text('Abrir investigación'),
              ),
            )),
            if (_selectedDetail != null)
              FutureBuilder<PrivateResearchCycleDetail>(
                future: _selectedDetail,
                builder: (context, detailSnapshot) {
                  if (detailSnapshot.connectionState != ConnectionState.done) {
                    return const Text('Verificando investigación privada…',
                        key: Key('private-research-detail-loading'));
                  }
                  if (detailSnapshot.hasError || !detailSnapshot.hasData) {
                    return const Text('No se pudo verificar esta investigación privada.',
                        key: Key('private-research-detail-error'));
                  }
                  final detail = detailSnapshot.data!;
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Investigación privada verificada (solo lectura)',
                          key: Key('private-research-detail')),
                      Text('Empresa: ${detail.symbol}'),
                      Text('Corte PIT: ${detail.asOf.toUtc().toIso8601String()}'),
                      Text('Ciclo: ${detail.cycleHash}'),
                      const Text('Las síntesis News y ATHENA requieren comprobación independiente.'),
                    ],
                  );
                },
              ),
            const Text('El listado no acredita licencias, ejecución de modelos ni autorización de trading.'),
          ],
        );
      },
    );
  }
}
