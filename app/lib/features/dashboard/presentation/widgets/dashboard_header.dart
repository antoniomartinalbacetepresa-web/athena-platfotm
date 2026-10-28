import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../../../../core/routing/app_routes.dart';

class DashboardHeader extends StatelessWidget {
  const DashboardHeader({super.key, this.onReturnFromRoute, this.onRefresh});

  /// Called after a primary route is popped, so owner-scoped Dashboard
  /// projections can re-read changes made in Profile or Portfolio.
  final ValueChanged<String>? onReturnFromRoute;

  /// Explicitly refreshes Dashboard evidence without changing route or authority.
  final VoidCallback? onRefresh;

  static const double _compactBreakpoint = 620;

  Future<void> _navigate(BuildContext context, String route) async {
    await Navigator.of(context).pushNamed<void>(route);
    if (context.mounted) onReturnFromRoute?.call(route);
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < _compactBreakpoint;
          return Row(
            children: [
              if (compact)
                Expanded(
                  child: Align(
                    alignment: Alignment.centerLeft,
                    child: SvgPicture.asset(
                      'assets/branding/athena_logo_wordmark.svg',
                      height: 42,
                      fit: BoxFit.contain,
                    ),
                  ),
                )
              else
                SvgPicture.asset(
                  'assets/branding/athena_logo_wordmark.svg',
                  height: 42,
                ),
              if (!compact) const Spacer(),
              if (compact)
                PopupMenuButton<String>(
                  tooltip: 'Navegación',
                  icon: const Icon(Icons.menu_rounded, color: Colors.white),
                  onSelected: (route) => unawaited(_navigate(context, route)),
                  itemBuilder: (_) => const [
                    PopupMenuItem(value: AppRoutes.market, child: Text('Mercado')),
                    PopupMenuItem(value: AppRoutes.news, child: Text('Noticias')),
                    PopupMenuItem(value: AppRoutes.investors, child: Text('Inversores')),
                    PopupMenuItem(value: AppRoutes.portfolio, child: Text('Cartera')),
                    PopupMenuItem(value: AppRoutes.profile, child: Text('Perfil')),
                  ],
                )
              else ...[
                _RouteButton(
                  tooltip: 'Mercado',
                  onPressed: () => unawaited(_navigate(context, AppRoutes.market)),
                  icon: Icons.public_rounded,
                ),
                _RouteButton(
                  tooltip: 'Noticias',
                  onPressed: () => unawaited(_navigate(context, AppRoutes.news)),
                  icon: Icons.article_outlined,
                ),
                _RouteButton(
                  tooltip: 'Inversores',
                  onPressed: () => unawaited(_navigate(context, AppRoutes.investors)),
                  icon: Icons.account_balance_outlined,
                ),
                _RouteButton(
                  tooltip: 'Cartera',
                  onPressed: () => unawaited(_navigate(context, AppRoutes.portfolio)),
                  icon: Icons.account_balance_wallet_outlined,
                ),
                _RouteButton(
                  tooltip: 'Perfil',
                  onPressed: () => unawaited(_navigate(context, AppRoutes.profile)),
                  icon: Icons.person_outline_rounded,
                ),
              ],
              if (onRefresh != null)
                IconButton(
                  key: const Key('dashboard-refresh-all'),
                  tooltip: 'Actualizar paneles del Dashboard',
                  onPressed: onRefresh,
                  icon: const Icon(Icons.refresh_rounded, color: Colors.white),
                ),
              const SizedBox(width: 8),
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: 0.08),
                  borderRadius: BorderRadius.circular(14),
                ),
                child: const Icon(Icons.notifications_none_rounded, color: Colors.white),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _RouteButton extends StatelessWidget {
  const _RouteButton({required this.tooltip, required this.onPressed, required this.icon});

  final String tooltip;
  final VoidCallback onPressed;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return IconButton(
      tooltip: tooltip,
      onPressed: onPressed,
      icon: Icon(icon, color: Colors.white),
    );
  }
}
