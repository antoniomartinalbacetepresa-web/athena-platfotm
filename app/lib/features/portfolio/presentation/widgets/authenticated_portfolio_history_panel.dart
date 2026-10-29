import 'dart:async';

import 'package:flutter/material.dart';

import '../../../auth/services/athena_auth_service.dart';
import '../../../auth/services/auth_session.dart';
import '../../models/authenticated_portfolio_history.dart';
import '../../services/authenticated_portfolio_service.dart';

class AuthenticatedPortfolioHistoryPanel extends StatefulWidget {
  const AuthenticatedPortfolioHistoryPanel({
    super.key,
    this.service,
    this.session,
    this.portfolioId = 'primary',
  });

  final AuthenticatedPortfolioService? service;
  final AuthSession? session;
  final String portfolioId;

  @override
  State<AuthenticatedPortfolioHistoryPanel> createState() =>
      _AuthenticatedPortfolioHistoryPanelState();
}

class _AuthenticatedPortfolioHistoryPanelState
    extends State<AuthenticatedPortfolioHistoryPanel> {
  late AuthenticatedPortfolioService _service;
  late AuthSession _session;
  late bool _ownsService;
  AuthenticatedPortfolioHistory? _history;
  Object? _error;
  bool _loading = true;
  bool _sessionRejected = false;
  bool _loadingMore = false;
  Object? _loadMoreError;
  int _requestVersion = 0;

  @override
  void initState() {
    super.initState();
    _ownsService = widget.service == null;
    _service = widget.service ?? AuthenticatedPortfolioService();
    _session = widget.session ?? AuthSession.instance;
    _session.addListener(_onSessionChanged);
    _load();
  }

  @override
  void didUpdateWidget(covariant AuthenticatedPortfolioHistoryPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.session != widget.session) {
      _session.removeListener(_onSessionChanged);
      _session = widget.session ?? AuthSession.instance;
      _session.addListener(_onSessionChanged);
    }
    if (oldWidget.service != widget.service) {
      if (_ownsService) _service.dispose();
      _ownsService = widget.service == null;
      _service = widget.service ??
          AuthenticatedPortfolioService(session: _session);
    } else if (oldWidget.session != widget.session && _ownsService) {
      _service.dispose();
      _service = AuthenticatedPortfolioService(session: _session);
    }
    if (oldWidget.portfolioId != widget.portfolioId ||
        oldWidget.session != widget.session ||
        oldWidget.service != widget.service) {
      _load();
    }
  }

  @override
  void dispose() {
    _requestVersion++;
    _session.removeListener(_onSessionChanged);
    if (_ownsService) _service.dispose();
    super.dispose();
  }

  void _onSessionChanged() {
    if (mounted) unawaited(_load());
  }

  Future<void> _load() async {
    final requestVersion = ++_requestVersion;
    final requestToken = _session.accessToken;
    final requestOwnerId = _session.account?.id;
    final requestPortfolioId = widget.portfolioId;

    if (!_session.isAuthenticated ||
        requestToken == null ||
        requestOwnerId == null) {
      setState(() {
        _history = null;
        _error = null;
        _loading = false;
        _sessionRejected = true;
        _loadingMore = false;
        _loadMoreError = null;
      });
      return;
    }

    setState(() {
      // Never render one owner's or portfolio's events while a new request
      // is pending, including after logout, login or portfolioId changes.
      _history = null;
      _loading = true;
      _error = null;
      _sessionRejected = false;
      _loadingMore = false;
      _loadMoreError = null;
    });

    bool isCurrent() =>
        mounted &&
        requestVersion == _requestVersion &&
        _session.isAuthenticated &&
        _session.accessToken == requestToken &&
        _session.account?.id == requestOwnerId &&
        widget.portfolioId == requestPortfolioId;

    try {
      final history = await _service.loadHistory(
        portfolioId: requestPortfolioId,
      );
      if (!isCurrent()) return;
      if (history.portfolioId != requestPortfolioId) {
        throw const FormatException(
          'El historial recibido pertenece a otra cartera.',
        );
      }
      setState(() {
        _history = history;
        _loading = false;
      });
    } on AuthSessionRejectedException catch (error) {
      // The authenticated service invalidates only the token that received
      // the rejection. A stale 401 must never clear a replacement session.
      if (!isCurrent()) return;
      setState(() {
        _history = null;
        _error = error;
        _sessionRejected = true;
        _loading = false;
      });
    } catch (error) {
      if (!isCurrent()) return;
      setState(() {
        _history = null;
        _error = error;
        _loading = false;
      });
    }
  }


  Future<void> _loadMore() async {
    final current = _history;
    final cursor = current?.nextCursor;
    if (_loading || _loadingMore || current == null ||
        !current.hasMore || cursor == null) return;
    final version = _requestVersion;
    final token = _session.accessToken;
    final ownerId = _session.account?.id;
    final portfolioId = widget.portfolioId;
    if (!_session.isAuthenticated || token == null || ownerId == null) return;
    setState(() { _loadingMore = true; _loadMoreError = null; });
    bool stillCurrent() => mounted && version == _requestVersion &&
        identical(_history, current) && _session.isAuthenticated &&
        _session.accessToken == token && _session.account?.id == ownerId &&
        widget.portfolioId == portfolioId;
    try {
      final page = await _service.loadHistory(
        portfolioId: portfolioId, asOf: current.asOf, cursor: cursor);
      if (!stillCurrent()) return;
      if (page.portfolioId != current.portfolioId ||
          !page.asOf.isAtSameMomentAs(current.asOf) ||
          page.events.isEmpty ||
          (page.hasMore && page.nextCursor == cursor)) {
        throw const FormatException('La página de historial no coincide.');
      }
      final hashes = current.events.map((event) => event.recordHash).toSet();
      if (page.events.any((event) => hashes.contains(event.recordHash))) {
        throw const FormatException('Historial duplicado.');
      }
      final previous = current.events.last;
      final next = page.events.first;
      final chronological = next.occurredAt.compareTo(previous.occurredAt);
      final availability = next.availableAt.compareTo(previous.availableAt);
      if (chronological > 0 ||
          (chronological == 0 && availability > 0) ||
          (chronological == 0 && availability == 0 &&
              next.sequence >= previous.sequence)) {
        throw const FormatException('Historial fuera de orden.');
      }
      setState(() {
        _history = AuthenticatedPortfolioHistory(
          portfolioId: current.portfolioId,
          asOf: current.asOf,
          events: List.unmodifiable([...current.events, ...page.events]),
          hasMore: page.hasMore,
          nextCursor: page.nextCursor,
        );
        _loadingMore = false;
      });
    } catch (error) {
      if (!stillCurrent()) return;
      setState(() { _loadingMore = false; _loadMoreError = error; });
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Semantics(
              container: true,
              header: true,
              label: 'Historial de cartera autenticado',
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      'Historial de cartera',
                      style: theme.textTheme.titleLarge,
                    ),
                  ),
                  IconButton(
                    tooltip: 'Cerrar historial',
                    onPressed: () => Navigator.of(context).maybePop(),
                    icon: const Icon(Icons.close),
                  ),
                ],
              ),
            ),
            Semantics(
              container: true,
              label: 'Historial de solo lectura. No ejecuta operaciones ni órdenes.',
              child: const Text(
                'Fuente: Event Ledger autenticado. Solo lectura; no envía órdenes.',
              ),
            ),
            const SizedBox(height: 12),
            Expanded(child: _buildBody(theme)),
          ],
        ),
      ),
    );
  }

  Widget _buildBody(ThemeData theme) {
    if (_loading) {
      return Center(
        child: Semantics(
          liveRegion: true,
          label: 'Cargando historial de cartera',
          child: const CircularProgressIndicator(
            key: Key('portfolio-history-loading'),
          ),
        ),
      );
    }
    if (_sessionRejected) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.lock_outline),
            const SizedBox(height: 8),
            Semantics(
              liveRegion: true,
              label: 'Sesión no válida. Inicia sesión de nuevo para consultar el historial de la cuenta.',
              child: const Text(
                'Tu sesión ya no es válida. Inicia sesión de nuevo para consultar el historial de la cuenta.',
                key: Key('portfolio-history-session-rejected'),
                textAlign: TextAlign.center,
              ),
            ),
            const SizedBox(height: 12),
            FilledButton.tonalIcon(
              key: const Key('portfolio-history-session-rejected-close'),
              onPressed: () => Navigator.of(context).maybePop(),
              icon: const Icon(Icons.close),
              label: const Text('Cerrar'),
            ),
          ],
        ),
      );
    }
    if (_error != null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline),
            const SizedBox(height: 8),
            Semantics(
              liveRegion: true,
              label: 'Error al cargar el historial de la cuenta.',
              child: const Text(
                'No se pudo cargar el historial de la cuenta.',
                key: Key('portfolio-history-error'),
                textAlign: TextAlign.center,
              ),
            ),
            const SizedBox(height: 12),
            FilledButton.tonalIcon(
              key: const Key('portfolio-history-retry'),
              onPressed: _load,
              icon: const Icon(Icons.refresh),
              label: const Text('Reintentar'),
            ),
          ],
        ),
      );
    }

    final history = _history;
    if (history == null || history.events.isEmpty) {
      return const Center(
        child: Text(
          'Todavía no hay eventos registrados en esta cartera.',
          key: Key('portfolio-history-empty'),
          textAlign: TextAlign.center,
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.separated(
        key: const Key('portfolio-history-list'),
        physics: const AlwaysScrollableScrollPhysics(),
        itemCount: history.events.length + (history.hasMore ? 1 : 0),
        separatorBuilder: (_, _) => const Divider(height: 1),
        itemBuilder: (context, index) {
          if (index == history.events.length) {
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 16),
              child: Column(children: [
                if (_loadMoreError != null)
                  Semantics(
                    liveRegion: true,
                    label: 'No se pudieron cargar eventos anteriores.',
                    child: const Text(
                      'No se pudieron cargar eventos anteriores. Puedes reintentar.',
                      key: Key('portfolio-history-more-error'),
                    ),
                  ),
                if (_loadingMore)
                  const CircularProgressIndicator(
                    key: Key('portfolio-history-more-loading'),
                  )
                else if (history.nextCursor != null)
                  FilledButton.tonal(
                    key: const Key('portfolio-history-load-more'),
                    onPressed: _loadMore,
                    child: const Text('Cargar eventos anteriores'),
                  )
                else
                  const Text('No hay cursor verificable para continuar.'),
              ]),
            );
          }
          return _HistoryEventTile(event: history.events[index], theme: theme);
        },
      ),
    );
  }
}

class _HistoryEventTile extends StatelessWidget {
  const _HistoryEventTile({required this.event, required this.theme});

  final AuthenticatedPortfolioHistoryEvent event;
  final ThemeData theme;

  @override
  Widget build(BuildContext context) {
    final instrument = event.instrumentId;
    final quantity = event.quantity;
    final amount = event.amount;
    final details = <String>[
      ?instrument,
      if (quantity != null) 'Cantidad ${_number(quantity)}',
      if (amount != null) '${_number(amount)} ${event.currency}',
    ];
    return ListTile(
      key: Key('portfolio-history-event-${event.sequence}'),
      contentPadding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
      title: Text(_eventLabel(event.eventType)),
      subtitle: Text(
        [
          if (details.isNotEmpty) details.join(' · '),
          'Ocurrido: ${event.occurredAt.toIso8601String()}',
          'Disponible: ${event.availableAt.toIso8601String()}',
          'Fuente: ${event.source}',
        ].join('\n'),
      ),
      trailing: Text(
        '#${event.sequence}',
        style: theme.textTheme.labelMedium,
      ),
    );
  }

  static String _number(double value) {
    final rounded = value.roundToDouble();
    return value == rounded ? value.toInt().toString() : value.toString();
  }

  static String _eventLabel(String type) {
    switch (type) {
      case 'external_cash_flow':
        return 'Flujo de caja externo';
      case 'trade_execution':
        return 'Operación ejecutada';
      case 'cash_dividend':
        return 'Dividendo';
      case 'fee':
        return 'Comisión';
      case 'tax':
        return 'Impuesto';
      case 'split_adjustment':
        return 'Ajuste por split';
      case 'corporate_action':
        return 'Acción corporativa';
      default:
        return type;
    }
  }
}
