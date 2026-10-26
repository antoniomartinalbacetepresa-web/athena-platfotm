import 'dart:async';

import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../../auth/services/auth_session.dart';
import '../../../market/di/market_dependencies.dart';
import '../../../portfolio/models/authenticated_portfolio_view_position.dart';
import '../../../portfolio/presentation/controllers/authenticated_portfolio_capital_controller.dart';
import '../../../portfolio/presentation/controllers/authenticated_portfolio_controller.dart';
import '../../../portfolio/presentation/controllers/authenticated_portfolio_fx_valuation_controller.dart';
import '../../../portfolio/services/authenticated_portfolio_fx_valuation_service.dart';
import '../../../portfolio/services/authenticated_portfolio_service.dart';
import '../../../profile/services/user_preferences_service.dart';

/// Dashboard projection of the same server-owned holdings and encrypted
/// Profile capital used by the authenticated Portfolio page. Never reads the
/// unscoped local/guest PortfolioRepository or mixes currencies without FX.
class AuthenticatedMySpacePanel extends StatefulWidget {
  const AuthenticatedMySpacePanel({
    super.key,
    this.portfolioController,
    this.capitalController,
    this.fxValuationController,
  }) : assert(
          (portfolioController == null) == (capitalController == null),
          'Inject both owner-scoped controllers or neither.',
        );

  final AuthenticatedPortfolioController? portfolioController;
  final AuthenticatedPortfolioCapitalController? capitalController;
  final AuthenticatedPortfolioFxValuationController? fxValuationController;

  @override
  State<AuthenticatedMySpacePanel> createState() =>
      _AuthenticatedMySpacePanelState();
}

class _AuthenticatedMySpacePanelState extends State<AuthenticatedMySpacePanel> {
  MarketDependencies? _market;
  AuthenticatedPortfolioService? _service;
  UserPreferencesService? _preferences;
  late final AuthenticatedPortfolioController _portfolio;
  late final AuthenticatedPortfolioCapitalController _capital;
  late final bool _ownsControllers;
  AuthenticatedPortfolioFxValuationController? _fx;
  List<AuthenticatedPortfolioViewPosition>? _fxPositions;
  String? _fxCurrency;
  int? _fxAuthorityVersion;
  bool _fxRefreshScheduled = false;

  @override
  void initState() {
    super.initState();
    _ownsControllers = widget.portfolioController == null;
    if (_ownsControllers) {
      final market = MarketDependencies.create();
      final service = AuthenticatedPortfolioService();
      final preferences = UserPreferencesService();
      _market = market;
      _service = service;
      _preferences = preferences;
      _portfolio = AuthenticatedPortfolioController(
        portfolioService: service,
        marketRepository: market.repository,
      );
      _capital = AuthenticatedPortfolioCapitalController(
        preferencesService: preferences,
      );
    } else {
      _portfolio = widget.portfolioController!;
      _capital = widget.capitalController!;
    }
    if (_ownsControllers) {
      final source = _market?.backendFxDataSource;
      if (source != null) {
        _fx = AuthenticatedPortfolioFxValuationController(
          valuationService: AuthenticatedPortfolioFxValuationService(
            loadCurrentFxRate: ({
              required String baseCurrency,
              required String quoteCurrency,
            }) => source.getCurrentRate(
              baseCurrency: baseCurrency,
              quoteCurrency: quoteCurrency,
            ),
          ),
        );
      }
    } else {
      _fx = widget.fxValuationController;
    }
    _portfolio.addListener(_onChanged);
    _capital.addListener(_onChanged);
    _fx?.addListener(_onChanged);
    _scheduleFxRefresh();
    if (_ownsControllers && AuthSession.instance.isAuthenticated) {
      unawaited(_portfolio.load());
      unawaited(_capital.load());
    }
  }

  void _onChanged() {
    if (!mounted) return;
    setState(() {});
    _scheduleFxRefresh();
  }

  void _scheduleFxRefresh() {
    if (_fx == null || _fxRefreshScheduled) return;
    _fxRefreshScheduled = true;
    scheduleMicrotask(() {
      _fxRefreshScheduled = false;
      if (mounted) _refreshFx();
    });
  }

  void _refreshFx() {
    final fx = _fx;
    if (fx == null) return;
    final currency =
        _capital.hasVerifiedBaseCurrency ? _capital.currency : null;
    final valid = AuthSession.instance.isAuthenticated &&
        !_portfolio.isLoading &&
        !_capital.isLoading &&
        !_portfolio.sessionRejected &&
        !_capital.sessionRejected &&
        _portfolio.error == null &&
        _capital.error == null &&
        _portfolio.positions.isNotEmpty &&
        currency != null;
    if (!valid) {
      _fxPositions = null;
      _fxCurrency = null;
      _fxAuthorityVersion = null;
      if (fx.valuation != null || fx.isLoading || fx.error != null) {
        fx.clear();
      }
      return;
    }
    final positions = _portfolio.positions;
    final authority = AuthSession.instance.authorityVersion;
    if (identical(_fxPositions, positions) &&
        _fxCurrency == currency &&
        _fxAuthorityVersion == authority) {
      return;
    }
    _fxPositions = positions;
    _fxCurrency = currency;
    _fxAuthorityVersion = authority;
    unawaited(fx.load(positions: positions, baseCurrency: currency!));
  }

  @override
  void dispose() {
    _portfolio.removeListener(_onChanged);
    _capital.removeListener(_onChanged);
    _fx?.removeListener(_onChanged);
    if (_ownsControllers) _fx?.dispose();
    if (_ownsControllers) {
      _portfolio.dispose();
      _capital.dispose();
      _preferences?.dispose();
      _service?.dispose();
      _market?.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!AuthSession.instance.isAuthenticated ||
        _portfolio.sessionRejected ||
        _capital.sessionRejected) {
      return const Center(
        child: Text(
          'Inicia sesión de nuevo para consultar tu cartera protegida.',
          key: Key('dashboard-owner-session-rejected'),
          textAlign: TextAlign.center,
        ),
      );
    }
    if (_portfolio.isLoading || _capital.isLoading) {
      return const Center(
        child: Text(
          'Verificando posiciones y perfil protegidos…',
          key: Key('dashboard-owner-loading'),
          textAlign: TextAlign.center,
        ),
      );
    }
    if (_portfolio.error != null) {
      return const Center(
        child: Text(
          'No se pudo verificar la cartera autenticada. No se muestran cifras locales.',
          key: Key('dashboard-owner-error'),
          textAlign: TextAlign.center,
        ),
      );
    }

    final positions = _portfolio.positions;
    final baseCurrency =
        _capital.hasVerifiedBaseCurrency ? _capital.currency : null;
    final comparable = positions.isNotEmpty &&
        baseCurrency != null &&
        _portfolio.directlyComparableCurrency == baseCurrency;
    final fxValuation = _fx?.valuation;
    final verifiedFx = _fx?.hasVerifiedValuation == true &&
        fxValuation != null &&
        identical(_fxPositions, positions) &&
        _fxCurrency == baseCurrency &&
        _fxAuthorityVersion == AuthSession.instance.authorityVersion &&
        fxValuation.baseCurrency == baseCurrency &&
        fxValuation.positionsValued == positions.length;
    final current = verifiedFx
        ? fxValuation!.currentValueInBaseCurrency
        : comparable
            ? _portfolio.directlyComparableCurrentValue
            : null;
    final invested = comparable ? _portfolio.directlyComparableInvestedValue : null;
    // Today's FX can value current holdings, but cannot reconstruct the
    // historical acquisition-date FX needed for cross-currency P/L.
    final profitLoss = comparable && current != null && invested != null
        ? current - invested
        : null;
    final capital = _capital.hasVerifiedCapital ? _capital.availableCapital : null;
    // Concentration is listing-scoped, never issuer-scoped. It is only
    // meaningful when all positions have verified values in the Profile base
    // currency; mixed-currency holdings remain blocked without PIT FX.
    final concentration = comparable ? _listingConcentration(positions) : null;

    return SingleChildScrollView(
      key: const Key('dashboard-authenticated-my-space'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _row('Posiciones de cuenta', '${positions.length}',
              'Fuente: cartera autenticada del servidor'),
          const Divider(),
          _row(
            'Valor actual',
            current == null ? 'No disponible' : _money(current, baseCurrency!),
            current == null
                ? 'Requiere precios y FX verificables; sin suma multimoneda'
                : verifiedFx && fxValuation!.usesFx
                    ? 'Conversión FX actual verificada · no válida para coste histórico'
                    : 'Cotizaciones verificadas · moneda del Perfil',
          ),
          if (verifiedFx && fxValuation!.usesFx)
            Text(
              'FX: ${fxValuation!.fxEvidence.map((quote) => '${quote.baseCurrency}/${quote.quoteCurrency} · ${quote.sourceProvider}').join(' · ')}',
              style: const TextStyle(
                color: AthenaColors.textSecondary,
                fontSize: 11,
              ),
            ),
          const Divider(),
          _row(
            'Resultado no realizado',
            profitLoss == null ? 'No disponible' : _money(profitLoss, baseCurrency!),
            profitLoss == null
                ? 'Requiere coste declarado y FX histórico verificable; no se utiliza FX actual'
                : 'Valor actual menos coste declarado; no incluye comisiones',
          ),
          const Divider(),
          _row(
            'Concentración por cotización',
            concentration == null
                ? 'No disponible'
                : 'HHI ${concentration.hhi.toStringAsFixed(3)}',
            concentration == null
                ? 'Requiere valoraciones homogéneas en la moneda del Perfil'
                : '${concentration.effectiveCount.toStringAsFixed(2)} posiciones efectivas · '
                    'mayor ${concentration.largestListing} '
                    '${(concentration.largestWeight * 100).toStringAsFixed(1)} %. '
                    'No equivale a concentración por emisor.',
          ),
          const Divider(),
          _row(
            'Capital disponible',
            capital == null || baseCurrency == null
                ? 'No disponible'
                : _money(capital, baseCurrency),
            'Fuente: preferencias cifradas del Perfil; no se infiere de posiciones',
          ),
          const SizedBox(height: 10),
          const Text(
            'Vista informativa: no ejecuta órdenes ni cambia recomendaciones o pesos. '
            'Consulta Mi cartera para el detalle y las valoraciones FX verificadas.',
            style: TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 11,
              height: 1.4,
            ),
          ),
        ],
      ),
    );
  }

  /// HHI over canonical listing labels (symbol + exchange), not issuers.
  /// Duplicate rows for the same listing are aggregated before computing HHI.
  static ({
    double hhi,
    double effectiveCount,
    String largestListing,
    double largestWeight,
  })? _listingConcentration(List<AuthenticatedPortfolioViewPosition> positions) {
    if (positions.isEmpty) return null;
    final values = <String, double>{};
    for (final position in positions) {
      final value = position.currentValue;
      if (!value.isFinite || value <= 0) return null;
      final listing = '${position.symbol} (${position.exchange ?? 'sin mercado'})';
      values.update(listing, (previous) => previous + value,
          ifAbsent: () => value);
    }
    final total = values.values.fold<double>(0, (sum, value) => sum + value);
    if (!total.isFinite || total <= 0) return null;
    var hhi = 0.0;
    var largestWeight = 0.0;
    var largestListing = '';
    for (final entry in values.entries) {
      final weight = entry.value / total;
      hhi += weight * weight;
      if (weight > largestWeight) {
        largestWeight = weight;
        largestListing = entry.key;
      }
    }
    if (!hhi.isFinite || hhi <= 0) return null;
    return (
      hhi: hhi,
      effectiveCount: 1 / hhi,
      largestListing: largestListing,
      largestWeight: largestWeight,
    );
  }

  static String _money(double amount, String currency) =>
      '${amount.toStringAsFixed(2)} $currency';

  static Widget _row(String label, String value, String detail) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label,
              style: const TextStyle(
                  color: AthenaColors.textSecondary, fontSize: 12)),
          const SizedBox(height: 3),
          Text(value,
              style: const TextStyle(
                  color: AthenaColors.text,
                  fontWeight: FontWeight.bold,
                  fontSize: 17)),
          const SizedBox(height: 3),
          Text(detail,
              style: const TextStyle(
                  color: AthenaColors.textSecondary, fontSize: 11)),
        ],
      );
}
