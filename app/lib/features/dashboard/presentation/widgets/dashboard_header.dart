import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../../../../core/routing/app_routes.dart';

class DashboardHeader extends StatelessWidget {
  const DashboardHeader({super.key});

  static const double _compactBreakpoint = 620;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < _compactBreakpoint;
          return Row(
            children: [
              SvgPicture.asset(
                'assets/branding/athena_logo_wordmark.svg',
                height: 42,
              ),
              const Spacer(),
              if (compact)
                PopupMenuButton<String>(
                  tooltip: 'Navegación',
                  icon: const Icon(Icons.menu_rounded, color: Colors.white),
                  onSelected: (route) => Navigator.of(context).pushNamed(route),
                  itemBuilder: (_) => const [
                    PopupMenuItem(
                      value: AppRoutes.market,
                      child: Text('Mercado'),
                    ),
                    PopupMenuItem(
                      value: AppRoutes.news,
                      child: Text('Noticias'),
                    ),
                    PopupMenuItem(
                      value: AppRoutes.portfolio,
                      child: Text('Cartera'),
                    ),
                    PopupMenuItem(
                      value: AppRoutes.profile,
                      child: Text('Perfil'),
                    ),
                  ],
                )
              else ...[
                _RouteButton(
                  tooltip: 'Mercado',
                  route: AppRoutes.market,
                  icon: Icons.public_rounded,
                ),
                _RouteButton(
                  tooltip: 'Noticias',
                  route: AppRoutes.news,
                  icon: Icons.article_outlined,
                ),
                _RouteButton(
                  tooltip: 'Cartera',
                  route: AppRoutes.portfolio,
                  icon: Icons.account_balance_wallet_outlined,
                ),
                _RouteButton(
                  tooltip: 'Perfil',
                  route: AppRoutes.profile,
                  icon: Icons.person_outline_rounded,
                ),
              ],
              const SizedBox(width: 8),
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: 0.08),
                  borderRadius: BorderRadius.circular(14),
                ),
                child: const Icon(
                  Icons.notifications_none_rounded,
                  color: Colors.white,
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _RouteButton extends StatelessWidget {
  const _RouteButton({
    required this.tooltip,
    required this.route,
    required this.icon,
  });

  final String tooltip;
  final String route;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return IconButton(
      tooltip: tooltip,
      onPressed: () => Navigator.of(context).pushNamed(route),
      icon: Icon(icon, color: Colors.white),
    );
  }
}
