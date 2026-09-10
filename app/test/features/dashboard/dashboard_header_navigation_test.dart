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
}
