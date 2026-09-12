import 'package:flutter/material.dart';

import '../../models/authenticated_portfolio_history.dart';
import '../../services/authenticated_portfolio_service.dart';

class AuthenticatedPortfolioHistoryPanel extends StatefulWidget {
  const AuthenticatedPortfolioHistoryPanel({
    super.key,
    this.service,
    this.portfolioId = 'primary',
  });

  final AuthenticatedPortfolioService? service;
  final String portfolioId;

  @override
  State<AuthenticatedPortfolioHistoryPanel> createState() =>
      _AuthenticatedPortfolioHistoryPanelState();
}

class _AuthenticatedPortfolioHistoryPanelState
    extends State<AuthenticatedPortfolioHistoryPanel> {
  late final AuthenticatedPortfolioService _service;
  late final bool _ownsService;
  AuthenticatedPortfolioHistory? _history;
  Object? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _ownsService = widget.service == null;
    _service = widget.service ?? AuthenticatedPortfolioService();
    _load();
  }

  @override
  void dispose() {
    if (_ownsService) _service.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    if (mounted) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final history = await _service.loadHistory(portfolioId: widget.portfolioId);
      if (!mounted) return;
      setState(() {
        _history = history;
        _loading = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error;
        _loading = false;
      });
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
            Row(
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
            Text(
              'Fuente: Event Ledger autenticado. Solo lectura; no envía órdenes.',
              style: theme.textTheme.bodySmall,
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
      return const Center(
        child: CircularProgressIndicator(
          key: Key('portfolio-history-loading'),
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
            const Text(
              'No se pudo cargar el historial de la cuenta.',
              key: Key('portfolio-history-error'),
              textAlign: TextAlign.center,
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
        separatorBuilder: (_, __) => const Divider(height: 1),
        itemBuilder: (context, index) {
          if (index == history.events.length) {
            return const Padding(
              padding: EdgeInsets.symmetric(vertical: 16),
              child: Text(
                'Hay más eventos en el ledger. Refina el corte temporal o consulta una página posterior.',
                textAlign: TextAlign.center,
              ),
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
      if (instrument != null) instrument,
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
