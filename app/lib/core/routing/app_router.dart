import 'package:flutter/material.dart';

import '../../features/auth/presentation/pages/login_page.dart';
import '../../features/auth/presentation/pages/password_recovery_page.dart';
import '../../features/auth/presentation/pages/register_page.dart';
import '../../features/dashboard/presentation/pages/dashboard_page.dart';
import '../../features/market/presentation/pages/market_page.dart';
import '../../features/news/presentation/pages/news_page.dart';
import '../../features/portfolio/presentation/pages/authenticated_portfolio_page.dart';
import '../../features/profile/presentation/pages/profile_personalization_shell.dart';
import '../../features/welcome/presentation/pages/welcome_page.dart';
import 'app_routes.dart';

class AppRouter {
  static Route<dynamic> generate(RouteSettings settings) {
    final rawName = settings.name ?? AppRoutes.welcome;
    final uri = Uri.tryParse(rawName);
    final path = uri?.path ?? rawName;

    switch (path) {
      case AppRoutes.login:
        return MaterialPageRoute(
          settings: settings,
          builder: (_) => const LoginPage(),
        );

      case AppRoutes.register:
        return MaterialPageRoute(
          settings: settings,
          builder: (_) => const RegisterPage(),
        );

      case AppRoutes.recovery:
        final argumentToken = settings.arguments is String
            ? (settings.arguments! as String).trim()
            : null;
        final queryToken = uri?.queryParameters['token']?.trim();
        final initialToken = (queryToken != null && queryToken.isNotEmpty)
            ? queryToken
            : ((argumentToken != null && argumentToken.isNotEmpty)
                ? argumentToken
                : null);
        return MaterialPageRoute(
          settings: settings,
          builder: (_) => PasswordRecoveryPage(initialToken: initialToken),
        );

      case AppRoutes.dashboard:
        return MaterialPageRoute(
          settings: settings,
          builder: (_) => const DashboardPage(),
        );

      case AppRoutes.market:
        return MaterialPageRoute(
          settings: settings,
          builder: (_) => const MarketPage(),
        );

      case AppRoutes.news:
        return MaterialPageRoute(
          settings: settings,
          builder: (_) => const NewsPage(),
        );

      case AppRoutes.portfolio:
        return MaterialPageRoute(
          settings: settings,
          builder: (_) => const AuthenticatedPortfolioPage(),
        );

      case AppRoutes.profile:
        return MaterialPageRoute(
          settings: settings,
          builder: (_) => const ProfilePersonalizationShell(),
        );

      case AppRoutes.welcome:
      default:
        return MaterialPageRoute(
          settings: settings,
          builder: (_) => const WelcomePage(),
        );
    }
  }
}
