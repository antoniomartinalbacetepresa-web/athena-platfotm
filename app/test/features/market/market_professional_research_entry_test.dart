import 'package:app/core/routing/app_routes.dart';
import 'package:app/features/market/presentation/pages/market_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('Market keeps professional research closed until a symbol exists',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(home: MarketPage()),
    );
    await tester.pump();

    final button = find.byKey(const Key('market-open-professional-research'));
    expect(button, findsOneWidget);
    expect(tester.widget<FilledButton>(button).onPressed, isNull);

    await tester.enterText(find.byType(TextField), ' aapl ');
    await tester.pump();

    expect(tester.widget<FilledButton>(button).onPressed, isNotNull);
  });

  testWidgets('Market normalizes symbol before opening professional research',
      (tester) async {
    String? route;
    await tester.pumpWidget(
      MaterialApp(
        home: const MarketPage(),
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

    await tester.enterText(find.byType(TextField), ' aapl ');
    await tester.tap(find.byKey(const Key('market-open-professional-research')));
    await tester.pump();

    expect(route, '${AppRoutes.stockResearch}?symbol=AAPL');
  });
}
