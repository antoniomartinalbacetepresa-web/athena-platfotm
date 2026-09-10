import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../../../../core/routing/app_routes.dart';

class DashboardHeader extends StatelessWidget {
  const DashboardHeader({super.key});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24),
      child: Row(
        children: [
          SvgPicture.asset(
            'assets/branding/athena_logo_wordmark.svg',
            height: 42,
          ),
          const Spacer(),
          IconButton(
            tooltip: 'Noticias',
            onPressed: () => Navigator.of(context).pushNamed(AppRoutes.news),
            icon: const Icon(
              Icons.article_outlined,
              color: Colors.white,
            ),
          ),
          const SizedBox(width: 4),
          IconButton(
            tooltip: 'Perfil',
            onPressed: () => Navigator.of(context).pushNamed(AppRoutes.profile),
            icon: const Icon(
              Icons.person_outline_rounded,
              color: Colors.white,
            ),
          ),
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
      ),
    );
  }
}
