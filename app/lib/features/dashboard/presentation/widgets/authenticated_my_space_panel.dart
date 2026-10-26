import 'dart:async';

import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../../auth/services/auth_session.dart';
import '../../../market/di/market_dependencies.dart';
import '../../../portfolio/models/authenticated_portfolio_view_position.dart';
import '../../../portfolio/presentation/controllers/authenticated_portfolio_capital_controller.dart';
import '../../../portfolio/presentation/controllers/authenticated_portfolio_controller.dart';
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
  }) : assert(
          (portfolioController == null) == (capitalController == null),
          'Inject both owner-scoped controllers or neither.',
        );

  final AuthenticatedPortfolioController? portfolioController;
  final AuthenticatedPortfolioCapitalController? capitalController;

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
    _portfolio.addListener(_onChanged);
    _capital.addListener(_onChanged);
    if (_ownsControllers && AuthSession.instance.isAuthenticated) {
      unawaited(_portfolio.load());
      unawaited(_capital.load());
    }
  }

  void _onChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _portfolio.removeListener(_onChanged);
    _capital.removeListener(_onChanged);
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
    final current = comparable ? _portfolio.directlyComparableCurrentValue : null;
    final invested = comparable ? _portfolio.directlyComparableInvestedValue : null;
    final profitLoss = current != null && invested != null
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
                ? 'Requiere precios y moneda base verificables; sin suma multimoneda'
                : 'Cotizaciones verificadas · moneda del Perfil',
          ),
          const Divider(),
          _row(
            'Resultado no realizado',
            profitLoss == null ? 'No disponible' : _money(profitLoss, baseCurrency!),
            profitLoss == null
                ? 'Requiere coste declarado y moneda comparable verificable'
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
