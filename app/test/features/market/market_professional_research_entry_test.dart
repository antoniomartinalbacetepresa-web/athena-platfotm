import 'package:app/core/routing/app_routes.dart';
import 'package:app/features/market/controllers/global_market_context_controller.dart';
import 'package:app/features/market/models/global_market_context.dart';
import 'package:app/features/market/presentation/pages/market_page.dart';
import 'package:app/features/market/di/market_dependencies.dart';
import 'package:app/features/market/services/global_market_data_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class _IdleMarketService extends GlobalMarketDataService {
  _IdleMarketService(MarketDependencies dependencies)
      : super(
          regionalMarketContextService: dependencies.regionalMarketContextService,
          globalMarketContextService: dependencies.globalMarketContextService,
          marketUniverseRepository: dependencies.marketUniverseRepository,
          regionalMarketWeightService: dependencies.regionalMarketWeightService,
          marketUniverseStatusProvider: dependencies.marketUniverseStatusProvider,
        );

  @override
  Future<GlobalMarketContext> getGlobalContext() =>
      Future<GlobalMarketContext>.error(StateError('test market unavailable'));
}

GlobalMarketContextController _controller() {
  final dependencies = MarketDependencies.create();
  return GlobalMarketContextController(
    service: _IdleMarketService(dependencies),
  );
}

void main() {
  testWidgets('Market keeps professional research closed until a symbol exists',
      (tester) async {
    final controller = _controller();
    addTearDown(controller.dispose);
    await tester.pumpWidget(MaterialApp(home: MarketPage(controller: controller)));
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
    final controller = _controller();
    addTearDown(controller.dispose);
    String? route;
    await tester.pumpWidget(
      MaterialApp(
        home: MarketPage(controller: controller),
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
    await tester.pump();
    await tester.tap(find.byKey(const Key('market-open-professional-research')));
    await tester.pump();

    expect(route, '${AppRoutes.stockResearch}?symbol=AAPL');
  });
}
