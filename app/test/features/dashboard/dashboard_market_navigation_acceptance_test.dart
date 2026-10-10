import 'package:app/core/routing/app_routes.dart';
import 'package:app/features/dashboard/presentation/widgets/dashboard_header.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('wide Dashboard opens the canonical Market route', (tester) async {
    String? route;
    await tester.pumpWidget(
      MaterialApp(
        home: const Scaffold(body: DashboardHeader()),
        onGenerateRoute: (settings) {
          route = settings.name;
          return MaterialPageRoute<void>(
            settings: settings,
            builder: (_) => const SizedBox(),
          );
        },
      ),
    );
    await tester.pump();

    await tester.tap(find.byTooltip('Mercado'));
    await tester.pump();

    expect(route, AppRoutes.market);
  });

  testWidgets('compact Dashboard keeps Market reachable through navigation',
      (tester) async {
    String? route;
    await tester.binding.setSurfaceSize(const Size(500, 800));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        home: const Scaffold(body: DashboardHeader()),
        onGenerateRoute: (settings) {
          route = settings.name;
          return MaterialPageRoute<void>(
            settings: settings,
            builder: (_) => const SizedBox(),
          );
        },
      ),
    );
    await tester.pump();

    await tester.tap(find.byTooltip('Navegación'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Mercado'));
    await tester.pumpAndSettle();

    expect(route, AppRoutes.market);
  });
}
