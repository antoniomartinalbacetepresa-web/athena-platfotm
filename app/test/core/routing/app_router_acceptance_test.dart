import 'package:app/core/routing/app_router.dart';
import 'package:app/core/routing/app_routes.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('AppRouter preserves identity for every primary named route', () {
    for (final name in const [
      AppRoutes.welcome,
      AppRoutes.login,
      AppRoutes.register,
      AppRoutes.dashboard,
      AppRoutes.market,
      AppRoutes.news,
      AppRoutes.portfolio,
      AppRoutes.profile,
    ]) {
      final route = AppRouter.generate(RouteSettings(name: name));
      expect(route.settings.name, name, reason: 'route identity lost for $name');
    }
  });

  test('recovery deep link preserves the complete named route identity', () {
    const name = '${AppRoutes.recovery}?token=opaque-token';
    final route = AppRouter.generate(const RouteSettings(name: name));

    expect(route.settings.name, name);
  });

  test('unknown route preserves requested identity while using safe fallback', () {
    const name = '/not-a-real-athena-route';
    final route = AppRouter.generate(const RouteSettings(name: name));

    expect(route.settings.name, name);
  });
}
