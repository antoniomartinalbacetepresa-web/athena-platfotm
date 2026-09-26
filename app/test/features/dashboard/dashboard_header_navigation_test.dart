import 'package:app/core/routing/app_routes.dart';
import 'package:app/features/dashboard/presentation/widgets/dashboard_header.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('dashboard header uses compact navigation on narrow screens', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(500, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: DashboardHeader()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byIcon(Icons.menu_rounded), findsOneWidget);
    expect(find.byTooltip('Mercado'), findsNothing);
  });

  testWidgets('dashboard header exposes direct navigation on wide screens', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: DashboardHeader()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byTooltip('Mercado'), findsOneWidget);
    expect(find.byTooltip('Noticias'), findsOneWidget);
    expect(find.byTooltip('Cartera'), findsOneWidget);
    expect(find.byTooltip('Perfil'), findsOneWidget);
  });

  testWidgets('wide dashboard navigation reaches every primary product route', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final visited = <String>[];
    await tester.pumpWidget(
      MaterialApp(
        home: const Scaffold(body: DashboardHeader()),
        onGenerateRoute: (settings) {
          visited.add(settings.name!);
          return MaterialPageRoute<void>(
            settings: settings,
            builder: (_) => Text('route:${settings.name}'),
          );
        },
      ),
    );

    for (final entry in const <String, String>{
      'Mercado': AppRoutes.market,
      'Noticias': AppRoutes.news,
      'Cartera': AppRoutes.portfolio,
      'Perfil': AppRoutes.profile,
    }.entries) {
      await tester.tap(find.byTooltip(entry.key));
      await tester.pumpAndSettle();
      expect(visited.last, entry.value);
      expect(find.text('route:${entry.value}'), findsOneWidget);
      Navigator.of(tester.element(find.text('route:${entry.value}'))).pop();
      await tester.pumpAndSettle();
    }
  });

  testWidgets('compact dashboard menu reaches every primary product route', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(500, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final visited = <String>[];
    await tester.pumpWidget(
      MaterialApp(
        home: const Scaffold(body: DashboardHeader()),
        onGenerateRoute: (settings) {
          visited.add(settings.name!);
          return MaterialPageRoute<void>(
            settings: settings,
            builder: (_) => Text('route:${settings.name}'),
          );
        },
      ),
    );

    for (final entry in const <String, String>{
      'Mercado': AppRoutes.market,
      'Noticias': AppRoutes.news,
      'Cartera': AppRoutes.portfolio,
      'Perfil': AppRoutes.profile,
    }.entries) {
      await tester.tap(find.byTooltip('Navegación'));
      await tester.pumpAndSettle();
      await tester.tap(find.text(entry.key));
      await tester.pumpAndSettle();
      expect(visited.last, entry.value);
      Navigator.of(tester.element(find.text('route:${entry.value}'))).pop();
      await tester.pumpAndSettle();
    }
  });
}
