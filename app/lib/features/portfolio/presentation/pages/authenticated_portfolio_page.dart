import 'package:flutter/material.dart';

import '../../../auth/services/auth_session.dart';
import '../../services/portfolio_service.dart';
import '../controllers/portfolio_cloud_sync_controller.dart';
import 'portfolio_page.dart';

/// Product-level Portfolio entry point.
///
/// The existing [PortfolioPage] remains the local evidence-rich portfolio UI.
/// This wrapper adds an explicit authenticated cloud-sync action without
/// changing local persistence semantics or enabling destructive background sync.
class AuthenticatedPortfolioPage extends StatefulWidget {
  const AuthenticatedPortfolioPage({super.key});

  @override
  State<AuthenticatedPortfolioPage> createState() =>
      _AuthenticatedPortfolioPageState();
}

class _AuthenticatedPortfolioPageState extends State<AuthenticatedPortfolioPage> {
  final PortfolioService _portfolioService = PortfolioService();
  late final PortfolioCloudSyncController _syncController;

  @override
  void initState() {
    super.initState();
    _syncController = PortfolioCloudSyncController()..addListener(_onSyncChanged);
  }

  @override
  void dispose() {
    _syncController.removeListener(_onSyncChanged);
    _syncController.dispose();
    super.dispose();
  }

  void _onSyncChanged() {
    if (mounted) setState(() {});
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
      await _portfolioService.loadPortfolio();
      final positions = _portfolioService.portfolio?.positions ?? const [];
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

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        const PortfolioPage(),
        Positioned(
          right: 20,
          bottom: 20,
          child: SafeArea(
            child: FloatingActionButton.extended(
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
          ),
        ),
      ],
    );
  }
}
