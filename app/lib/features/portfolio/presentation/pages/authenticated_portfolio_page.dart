import 'package:flutter/material.dart';

import '../../../auth/services/auth_session.dart';
import '../../models/portfolio_position.dart';
import '../../services/portfolio_service.dart';
import '../controllers/portfolio_cloud_sync_controller.dart';
import '../widgets/authenticated_portfolio_history_panel.dart';
import 'portfolio_page.dart';

typedef PortfolioPositionsLoader = Future<List<PortfolioPosition>> Function();

/// Product-level Portfolio entry point.
///
/// The existing [PortfolioPage] remains the local evidence-rich portfolio UI.
/// This wrapper adds explicit authenticated cloud sync and a read-only view over
/// the owner-scoped append-only Event Ledger. Neither action enables trading.
class AuthenticatedPortfolioPage extends StatefulWidget {
  const AuthenticatedPortfolioPage({
    super.key,
    this.positionsLoader,
    this.syncController,
    this.child,
  });

  final PortfolioPositionsLoader? positionsLoader;
  final PortfolioCloudSyncController? syncController;
  final Widget? child;

  @override
  State<AuthenticatedPortfolioPage> createState() =>
      _AuthenticatedPortfolioPageState();
}

class _AuthenticatedPortfolioPageState extends State<AuthenticatedPortfolioPage> {
  final PortfolioService _portfolioService = PortfolioService();
  late final PortfolioCloudSyncController _syncController;
  late final bool _ownsSyncController;

  @override
  void initState() {
    super.initState();
    _ownsSyncController = widget.syncController == null;
    _syncController = widget.syncController ?? PortfolioCloudSyncController();
    _syncController.addListener(_onSyncChanged);
  }

  @override
  void dispose() {
    _syncController.removeListener(_onSyncChanged);
    if (_ownsSyncController) _syncController.dispose();
    super.dispose();
  }

  void _onSyncChanged() {
    if (mounted) setState(() {});
  }

  Future<List<PortfolioPosition>> _loadDeclaredPositions() async {
    final injectedLoader = widget.positionsLoader;
    if (injectedLoader != null) {
      return List<PortfolioPosition>.unmodifiable(await injectedLoader());
    }
    await _portfolioService.loadPortfolio();
    return List<PortfolioPosition>.unmodifiable(
      _portfolioService.portfolio?.positions ?? const <PortfolioPosition>[],
    );
  }

  Future<void> _syncDeclaredPositions() async {
    if (_syncController.isSyncing) return;
    if (!AuthSession.instance.isAuthenticated) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Inicia sesión para sincronizar posiciones con tu cuenta ATHENA.',
          ),
        ),
      );
      return;
    }

    try {
      final positions = await _loadDeclaredPositions();
      await _syncController.sync(positions);
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'No se pudo leer la cartera local. No se ha enviado ningún dato.',
          ),
        ),
      );
      return;
    }

    if (!mounted || _syncController.message == null) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(_syncController.message!)),
    );
  }

  Future<void> _openAuthenticatedHistory() async {
    if (!AuthSession.instance.isAuthenticated) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Inicia sesión para consultar el historial de tu cuenta ATHENA.',
          ),
        ),
      );
      return;
    }
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (context) => const FractionallySizedBox(
        heightFactor: 0.78,
        child: AuthenticatedPortfolioHistoryPanel(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        widget.child ?? const PortfolioPage(),
        Positioned(
          right: 20,
          bottom: 20,
          child: SafeArea(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                FloatingActionButton.small(
                  key: const Key('portfolio-authenticated-history'),
                  heroTag: 'portfolio-authenticated-history',
                  tooltip: 'Historial de cuenta',
                  onPressed: _openAuthenticatedHistory,
                  child: const Icon(Icons.history),
                ),
                const SizedBox(height: 12),
                FloatingActionButton.extended(
                  key: const Key('portfolio-authenticated-sync'),
                  heroTag: 'portfolio-authenticated-sync',
                  onPressed:
                      _syncController.isSyncing ? null : _syncDeclaredPositions,
                  icon: _syncController.isSyncing
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.cloud_upload_outlined),
                  label: Text(
                    _syncController.isSyncing
                        ? 'Sincronizando…'
                        : 'Sincronizar cuenta',
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
