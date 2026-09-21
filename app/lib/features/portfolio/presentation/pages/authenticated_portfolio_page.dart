import 'dart:async';

import 'package:flutter/material.dart';

import '../../../auth/services/auth_session.dart';
import '../../../market/di/market_dependencies.dart';
import '../../../profile/services/user_preferences_service.dart';
import '../../models/authenticated_portfolio_view_position.dart';
import '../../models/portfolio_position.dart';
import '../../services/authenticated_portfolio_fx_valuation_service.dart';
import '../../services/authenticated_portfolio_service.dart';
import '../../services/portfolio_service.dart';
import '../../widgets/add_position_dialog.dart';
import '../controllers/authenticated_portfolio_capital_controller.dart';
import '../controllers/authenticated_portfolio_controller.dart';
import '../controllers/authenticated_portfolio_fx_valuation_controller.dart';
import '../controllers/portfolio_cloud_sync_controller.dart';
import '../widgets/authenticated_portfolio_capital_view.dart';
import '../widgets/authenticated_portfolio_history_panel.dart';
import '../widgets/authenticated_portfolio_view.dart';
import 'portfolio_page.dart';

typedef PortfolioPositionsLoader = Future<List<PortfolioPosition>> Function();

class AuthenticatedPortfolioPage extends StatefulWidget {
  const AuthenticatedPortfolioPage({
    super.key,
    this.positionsLoader,
    this.syncController,
    this.historyService,
    this.child,
  });

  final PortfolioPositionsLoader? positionsLoader;
  final PortfolioCloudSyncController? syncController;
  final AuthenticatedPortfolioService? historyService;
  final Widget? child;

  @override
  State<AuthenticatedPortfolioPage> createState() => _AuthenticatedPortfolioPageState();
}

class _AuthenticatedPortfolioPageState extends State<AuthenticatedPortfolioPage> {
  final PortfolioService _portfolioService = PortfolioService();
  late final PortfolioCloudSyncController _syncController;
  late final bool _ownsSyncController;

  MarketDependencies? _marketDependencies;
  AuthenticatedPortfolioService? _authenticatedService;
  AuthenticatedPortfolioController? _authenticatedController;
  UserPreferencesService? _preferencesService;
  AuthenticatedPortfolioCapitalController? _capitalController;
  AuthenticatedPortfolioFxValuationController? _fxValuationController;
  bool _valuationRefreshScheduled = false;

  bool get _usesLegacyInjectedBoundary =>
      widget.positionsLoader != null || widget.syncController != null || widget.child != null;

  @override
  void initState() {
    super.initState();
    AuthSession.instance.addListener(_onSessionAuthorityChanged);
    _ownsSyncController = widget.syncController == null;
    _syncController = widget.syncController ?? PortfolioCloudSyncController();
    _syncController.addListener(_onSyncChanged);

    if (!_usesLegacyInjectedBoundary && AuthSession.instance.isAuthenticated) {
      final market = MarketDependencies.create();
      final service = AuthenticatedPortfolioService();
      final controller = AuthenticatedPortfolioController(
        portfolioService: service,
        marketRepository: market.repository,
      );
      final preferencesService = UserPreferencesService();
      final capitalController = AuthenticatedPortfolioCapitalController(
        preferencesService: preferencesService,
      );
      final fxDataSource = market.backendFxDataSource;
      final fxController = fxDataSource == null
          ? null
          : AuthenticatedPortfolioFxValuationController(
              valuationService: AuthenticatedPortfolioFxValuationService(
                loadCurrentFxRate: ({
                  required String baseCurrency,
                  required String quoteCurrency,
                }) => fxDataSource.getCurrentRate(
                  baseCurrency: baseCurrency,
                  quoteCurrency: quoteCurrency,
                ),
              ),
            );
      _marketDependencies = market;
      _authenticatedService = service;
      _authenticatedController = controller;
      _preferencesService = preferencesService;
      _capitalController = capitalController;
      _fxValuationController = fxController;
      controller.addListener(_onAuthenticatedChanged);
      capitalController.addListener(_onAuthenticatedChanged);
      fxController?.addListener(_onFxChanged);
      unawaited(controller.load());
      unawaited(capitalController.load());
    }
  }

  @override
  void dispose() {
    AuthSession.instance.removeListener(_onSessionAuthorityChanged);
    _fxValuationController?.removeListener(_onFxChanged);
    _fxValuationController?.dispose();
    _capitalController?.removeListener(_onAuthenticatedChanged);
    _capitalController?.dispose();
    _preferencesService?.dispose();
    _authenticatedController?.removeListener(_onAuthenticatedChanged);
    _authenticatedController?.dispose();
    _authenticatedService?.dispose();
    _marketDependencies?.dispose();
    _syncController.removeListener(_onSyncChanged);
    if (_ownsSyncController) _syncController.dispose();
    super.dispose();
  }

  void _onSessionAuthorityChanged() {
    // Session revocation/logout is an authority change, not merely persisted
    // state. Rebuild immediately so protected controls and owner data disappear
    // without waiting for an unrelated widget event or navigation cycle.
    if (mounted) setState(() {});
  }

  void _onSyncChanged() {
    if (mounted) setState(() {});
  }

  void _onAuthenticatedChanged() {
    _scheduleVerifiedValuationRefresh();
    if (mounted) setState(() {});
  }

  void _onFxChanged() {
    if (mounted) setState(() {});
  }

  void _scheduleVerifiedValuationRefresh() {
    if (_valuationRefreshScheduled) return;
    _valuationRefreshScheduled = true;
    scheduleMicrotask(() {
      _valuationRefreshScheduled = false;
      if (!mounted) return;
      final holdings = _authenticatedController;
      final profile = _capitalController;
      final fx = _fxValuationController;
      if (holdings == null || profile == null || fx == null ||
          holdings.isLoading || profile.isLoading) {
        return;
      }
      final currency = profile.currency;
      if (holdings.sessionRejected || profile.sessionRejected ||
          holdings.error != null || profile.error != null ||
          holdings.positions.isEmpty || !profile.hasVerifiedBaseCurrency || currency == null) {
        fx.clear();
        return;
      }
      unawaited(fx.load(positions: holdings.positions, baseCurrency: currency));
    });
  }

  Future<List<PortfolioPosition>> _loadDeclaredPositions() async {
    final injectedLoader = widget.positionsLoader;
    if (injectedLoader != null) return List<PortfolioPosition>.unmodifiable(await injectedLoader());
    await _portfolioService.loadPortfolio();
    return List<PortfolioPosition>.unmodifiable(
      _portfolioService.portfolio?.positions ?? const <PortfolioPosition>[],
    );
  }

  Future<void> _syncDeclaredPositions() async {
    if (_syncController.isSyncing || !AuthSession.instance.isAuthenticated) return;
    final authorityToken = AuthSession.instance.accessToken?.trim();
    if (authorityToken == null || authorityToken.isEmpty) return;
    try {
      final positions = await _loadDeclaredPositions();
      if (!AuthSession.instance.isAuthenticated ||
          AuthSession.instance.accessToken?.trim() != authorityToken) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text(
            'La cuenta ATHENA cambió mientras se preparaba la sincronización. '
            'No se ha enviado ningún dato.',
          ),
        ));
        return;
      }
      await _syncController.sync(positions);
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('No se pudo leer la cartera local. No se ha enviado ningún dato.'),
      ));
      return;
    }
    if (!mounted) return;
    setState(() {});
    if (_syncController.message != null) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_syncController.message!)));
    }
  }

  Future<void> _openAuthenticatedHistory() async {
    if (!AuthSession.instance.isAuthenticated) return;
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (context) => FractionallySizedBox(
        heightFactor: 0.78,
        child: AuthenticatedPortfolioHistoryPanel(service: widget.historyService ?? _authenticatedService),
      ),
    );
    if (mounted) setState(() {});
  }

  Future<void> _addAuthenticatedPosition() async {
    final controller = _authenticatedController;
    final market = _marketDependencies;
    if (controller == null || market == null || controller.sessionRejected) return;
    final result = await showDialog<AddPositionResult>(
      context: context,
      builder: (context) => AddPositionDialog(marketRepository: market.repository),
    );
    if (result == null) return;
    final saved = await controller.upsert(
      symbol: result.symbol,
      exchange: result.exchange,
      quantity: result.shares,
      averagePurchasePrice: result.averagePrice,
    );
    if (!mounted || saved) return;
    if (!controller.sessionRejected) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(controller.error ?? 'No se pudo guardar la posición.')),
      );
    }
  }

  Future<void> _removeAuthenticatedPosition(AuthenticatedPortfolioViewPosition position) async {
    final controller = _authenticatedController;
    if (controller == null || controller.sessionRejected) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Eliminar posición'),
        content: Text('¿Quieres eliminar ${position.companyName} (${position.symbol}) de tu cuenta ATHENA?'),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancelar')),
          ElevatedButton(onPressed: () => Navigator.of(context).pop(true), child: const Text('Eliminar')),
        ],
      ),
    );
    if (confirmed != true) return;
    final removed = await controller.remove(position);
    if (!mounted || removed) return;
    if (!controller.sessionRejected) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(controller.error ?? 'No se pudo eliminar la posición.')),
      );
    }
  }

  Widget _buildAuthoritativeAuthenticatedPortfolio() {
    final controller = _authenticatedController;
    final capitalController = _capitalController;
    if (controller == null || capitalController == null) {
      return const Scaffold(body: SafeArea(child: Center(child: Text('No se pudo inicializar la cartera autenticada.'))));
    }
    final verifiedBaseCurrency = capitalController.hasVerifiedBaseCurrency
        ? capitalController.currency
        : null;
    return Scaffold(
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 1200),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(children: [
                    IconButton(tooltip: 'Volver', onPressed: () => Navigator.of(context).maybePop(), icon: const Icon(Icons.arrow_back_rounded)),
                    const SizedBox(width: 8),
                    const Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('MI CARTERA', style: TextStyle(fontSize: 30, fontWeight: FontWeight.bold)),
                      Text('Posiciones personales protegidas por tu cuenta ATHENA'),
                    ])),
                    IconButton(
                      key: const Key('portfolio-authenticated-history'),
                      tooltip: 'Historial de cuenta',
                      onPressed: controller.sessionRejected ? null : _openAuthenticatedHistory,
                      icon: const Icon(Icons.history),
                    ),
                  ]),
                  const SizedBox(height: 20),
                  AuthenticatedPortfolioCapitalView(controller: capitalController, onRetry: capitalController.load),
                  const SizedBox(height: 12),
                  AuthenticatedPortfolioView(
                    controller: controller,
                    fxValuationController: _fxValuationController,
                    verifiedBaseCurrency: verifiedBaseCurrency,
                    onRetry: controller.load,
                    onAdd: _addAuthenticatedPosition,
                    onRemove: _removeAuthenticatedPosition,
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildLegacyMigrationBoundary() {
    final isAuthenticated = AuthSession.instance.isAuthenticated;
    return Stack(children: [
      widget.child ?? const PortfolioPage(),
      Positioned(
        right: 20,
        bottom: 20,
        child: SafeArea(child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.end, children: [
          if (!isAuthenticated) ...[
            const Card(key: Key('portfolio-authentication-required'), child: Padding(
              padding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              child: Text('Inicia sesión para usar el historial y la sincronización de cuenta.', textAlign: TextAlign.center),
            )),
            const SizedBox(height: 8),
          ],
          FloatingActionButton.small(
            key: const Key('portfolio-authenticated-history'),
            heroTag: 'portfolio-authenticated-history',
            tooltip: isAuthenticated ? 'Historial de cuenta' : 'Inicia sesión para consultar el historial',
            onPressed: isAuthenticated ? _openAuthenticatedHistory : null,
            child: const Icon(Icons.history),
          ),
          const SizedBox(height: 12),
          FloatingActionButton.extended(
            key: const Key('portfolio-authenticated-sync'),
            heroTag: 'portfolio-authenticated-sync',
            onPressed: !isAuthenticated || _syncController.isSyncing ? null : _syncDeclaredPositions,
            icon: _syncController.isSyncing
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.cloud_upload_outlined),
            label: Text(!isAuthenticated ? 'Inicia sesión' : _syncController.isSyncing ? 'Sincronizando…' : 'Sincronizar cuenta'),
          ),
        ])),
      ),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    if (_usesLegacyInjectedBoundary) return _buildLegacyMigrationBoundary();
    if (AuthSession.instance.isAuthenticated) return _buildAuthoritativeAuthenticatedPortfolio();
    return const PortfolioPage();
  }
}
