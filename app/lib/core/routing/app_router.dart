import 'package:flutter/material.dart';

import '../../features/auth/presentation/pages/login_page.dart';
import '../../features/auth/presentation/pages/register_page.dart';
import '../../features/dashboard/presentation/pages/dashboard_page.dart';
import '../../features/market/presentation/pages/market_page.dart';
import '../../features/news/presentation/pages/news_page.dart';
import '../../features/portfolio/presentation/pages/portfolio_page.dart';
import '../../features/profile/presentation/pages/profile_page.dart';
import '../../features/welcome/presentation/pages/welcome_page.dart';
import 'app_routes.dart';

class AppRouter {
  static Route<dynamic> generate(RouteSettings settings) {
    switch (settings.name) {
      case AppRoutes.login:
        return MaterialPageRoute(
          builder: (_) => const LoginPage(),
        );

      case AppRoutes.register:
        return MaterialPageRoute(
          builder: (_) => const RegisterPage(),
        );

      case AppRoutes.dashboard:
        return MaterialPageRoute(
          builder: (_) => const DashboardPage(),
        );

      case AppRoutes.market:
        return MaterialPageRoute(
          builder: (_) => const MarketPage(),
        );

      case AppRoutes.news:
        return MaterialPageRoute(
          builder: (_) => const NewsPage(),
        );

      case AppRoutes.portfolio:
        return MaterialPageRoute(
          builder: (_) => const PortfolioPage(),
        );

      case AppRoutes.profile:
        return MaterialPageRoute(
          builder: (_) => const ProfilePage(),
        );

      case AppRoutes.welcome:
      default:
        return MaterialPageRoute(
          builder: (_) => const WelcomePage(),
        );
    }
  }
}
