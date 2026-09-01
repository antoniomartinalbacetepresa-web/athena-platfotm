import 'package:flutter/material.dart';

import '../../features/dashboard/presentation/pages/dashboard_page.dart';
import '../../features/portfolio/presentation/pages/portfolio_page.dart';
import '../../features/welcome/presentation/pages/welcome_page.dart';
import 'app_routes.dart';

class AppRouter {
  static Route<dynamic> generate(RouteSettings settings) {
    switch (settings.name) {
      case AppRoutes.dashboard:
        return MaterialPageRoute(
          builder: (_) => const DashboardPage(),
        );

      case AppRoutes.portfolio:
        return MaterialPageRoute(
          builder: (_) => const PortfolioPage(),
        );

      case AppRoutes.welcome:
      default:
        return MaterialPageRoute(
          builder: (_) => const WelcomePage(),
        );
    }
  }
}