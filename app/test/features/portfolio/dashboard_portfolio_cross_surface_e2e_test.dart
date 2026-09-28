import 'package:app/core/routing/app_routes.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/dashboard/presentation/widgets/dashboard_header.dart';
import 'package:app/features/portfolio/presentation/pages/authenticated_portfolio_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('dashboard reaches real Portfolio guest boundary', (tester) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    AuthSession.instance.clear();
    addTearDown(AuthSession.instance.clear);

    await tester.pumpWidget(MaterialApp(
      home: const Scaffold(body: DashboardHeader()),
      onGenerateRoute: (settings) {
        if (settings.name != AppRoutes.portfolio) return null;
        return MaterialPageRoute<void>(
          settings: settings,
          builder: (_) => const AuthenticatedPortfolioPage(
            child: SizedBox(key: Key('portfolio-route-content')),
          ),
        );
      },
    ));

    await tester.tap(find.byTooltip('Cartera'));
    await tester.pumpAndSettle();

    final content = find.byKey(const Key('portfolio-route-content'));
    expect(ModalRoute.of(tester.element(content))!.settings.name, AppRoutes.portfolio);
    expect(find.byKey(const Key('portfolio-authentication-required')), findsOneWidget);
    final sync = tester.widget<FloatingActionButton>(
      find.byKey(const Key('portfolio-authenticated-sync')),
    );
    expect(sync.onPressed, isNull);
  });
}
