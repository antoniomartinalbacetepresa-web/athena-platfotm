import 'dart:async';

import 'package:app/core/routing/app_routes.dart';
import 'package:app/features/dashboard/presentation/widgets/dashboard_header.dart';
import 'package:app/features/market/controllers/global_market_context_controller.dart';
import 'package:app/features/market/models/global_market_context.dart';
import 'package:app/features/market/models/market_region.dart';
import 'package:app/features/market/models/market_universe_asset.dart';
import 'package:app/features/market/models/regional_market_context.dart';
import 'package:app/features/market/presentation/pages/market_page.dart';
import 'package:app/features/market/repositories/market_universe_repository.dart';
import 'package:app/features/market/services/global_market_context_service.dart';
import 'package:app/features/market/services/global_market_data_service.dart';
import 'package:app/features/market/services/regional_market_context_service.dart';
import 'package:app/features/market/services/regional_market_weight_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class _RegionalService implements RegionalMarketContextService {
  @override
  Future<RegionalMarketContext> getRegionalContext({required MarketRegion region}) async =>
      RegionalMarketContext(
        region: region.key,
        displayName: region.key,
        assetsAnalyzed: 1,
        advancingPercentage: 100,
        decliningPercentage: 0,
        sentiment: 'positive',
        summary: region.key,
        updatedAt: DateTime.utc(2026, 9, 21, 3),
      );
}

class _UniverseRepository implements MarketUniverseRepository {
  const _UniverseRepository();

  @override
  Future<List<MarketUniverseAsset>> getUniverse() async => const [
        MarketUniverseAsset(
          symbol: 'USA',
          companyName: 'America Test Company',
          marketCap: 500,
          country: 'United States',
        ),
        MarketUniverseAsset(
          symbol: 'ESP',
          companyName: 'Europe Test Company',
          marketCap: 300,
          country: 'Spain',
        ),
        MarketUniverseAsset(
          symbol: 'JPN',
          companyName: 'Asia Test Company',
          marketCap: 200,
          country: 'Japan',
        ),
      ];
}

class _ControlledMarketService extends GlobalMarketDataService {
  _ControlledMarketService(this.responses)
      : super(
          regionalMarketContextService: _RegionalService(),
          globalMarketContextService: const GlobalMarketContextService(),
          marketUniverseRepository: const _UniverseRepository(),
          regionalMarketWeightService: const RegionalMarketWeightService(),
        );

  final List<Future<GlobalMarketContext>> responses;
  var calls = 0;

  @override
  Future<GlobalMarketContext> getGlobalContext() => responses[calls++];
}

Future<GlobalMarketContext> _context(String summary) async {
  final base = await GlobalMarketDataService(
    regionalMarketContextService: _RegionalService(),
    globalMarketContextService: const GlobalMarketContextService(),
    marketUniverseRepository: const _UniverseRepository(),
    regionalMarketWeightService: const RegionalMarketWeightService(),
  ).getGlobalContext();
  return GlobalMarketContext(
    updatedAt: base.updatedAt,
    america: base.america,
    europe: base.europe,
    asia: base.asia,
    americaWeight: base.americaWeight,
    europeWeight: base.europeWeight,
    asiaWeight: base.asiaWeight,
    weightSource: base.weightSource,
    weightConfidence: base.weightConfidence,
    marketUniverseStatus: base.marketUniverseStatus,
    advancingPercentage: base.advancingPercentage,
    decliningPercentage: base.decliningPercentage,
    sentiment: base.sentiment,
    summary: summary,
  );
}

void main() {
  testWidgets('Market page exposes the informational contract before data resolves', (tester) async {
    final pending = Completer<GlobalMarketContext>();
    final service = _ControlledMarketService([pending.future]);
    final controller = GlobalMarketContextController(service: service);

    await tester.pumpWidget(MaterialApp(home: MarketPage(controller: controller)));
    await tester.pump();

    expect(find.text('MERCADO'), findsOneWidget);
    expect(find.byKey(const Key('market-information-boundary')), findsOneWidget);
    expect(
      find.bySemanticsLabel(
        'Contexto de mercado informativo. Los datos pueden cambiar y no constituyen una recomendación ni ejecutan operaciones.',
      ),
      findsOneWidget,
    );
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(
      find.bySemanticsLabel('Actualizando contexto global del mercado.'),
      findsOneWidget,
    );
    final globalHeading = tester.widget<Semantics>(
      find.ancestor(
        of: find.text('MERCADO GLOBAL'),
        matching: find.byType(Semantics),
      ).first,
    );
    expect(globalHeading.properties.header, isTrue);

    await tester.pumpWidget(const SizedBox.shrink());
    controller.dispose();
  });

  testWidgets('Dashboard to Market reaches the real controlled informational surface', (tester) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final controlled = _ControlledMarketService([
      _context('Contexto E2E verificado'),
    ]);
    final controller = GlobalMarketContextController(service: controlled);
    addTearDown(controller.dispose);

    await tester.pumpWidget(
      MaterialApp(
        home: const Scaffold(body: DashboardHeader()),
        onGenerateRoute: (settings) {
          if (settings.name == AppRoutes.market) {
            return MaterialPageRoute<void>(
              settings: settings,
              builder: (_) => MarketPage(controller: controller),
            );
          }
          return null;
        },
      ),
    );

    await tester.tap(find.byTooltip('Mercado'));
    await tester.pumpAndSettle();

    expect(
      ModalRoute.of(tester.element(find.text('MERCADO')))!.settings.name,
      AppRoutes.market,
    );
    expect(find.text('Contexto E2E verificado'), findsOneWidget);
    expect(find.byKey(const Key('market-information-boundary')), findsOneWidget);
    expect(find.textContaining('no constituye una recomendación'), findsOneWidget);
    expect(controlled.calls, 1);
  });

  testWidgets('Market page hides stale snapshot while refresh is pending', (tester) async {
    final pending = Completer<GlobalMarketContext>();
    final initial = await _context('Snapshot inicial');
    final updated = await _context('Snapshot actualizado');
    final service = _ControlledMarketService([
      Future.value(initial),
      pending.future,
    ]);
    final controller = GlobalMarketContextController(service: service);

    await tester.pumpWidget(MaterialApp(home: MarketPage(controller: controller)));
    await tester.pumpAndSettle();
    expect(find.text('Snapshot inicial'), findsOneWidget);
    expect(find.byKey(const Key('market-information-boundary')), findsOneWidget);
    expect(
      find.bySemanticsLabel(
        'Contexto de mercado informativo. Los datos pueden cambiar y no constituyen una recomendación ni ejecutan operaciones.',
      ),
      findsOneWidget,
    );
    final heading = tester.widget<Semantics>(
      find.ancestor(
        of: find.text('MERCADO'),
        matching: find.byType(Semantics),
      ).first,
    );
    expect(heading.properties.header, isTrue);

    await tester.tap(find.byTooltip('Actualizar mercado'));
    await tester.pump();
    expect(find.text('Snapshot inicial'), findsNothing);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    pending.complete(updated);
    await tester.pumpAndSettle();
    expect(find.text('Snapshot actualizado'), findsOneWidget);
    expect(find.text('Snapshot inicial'), findsNothing);
    expect(service.calls, 2);

    controller.dispose();
  });

  testWidgets('Market page replaces injected controller without retaining prior snapshot', (tester) async {
    final initial = await _context('Contexto anterior');
    final pending = Completer<GlobalMarketContext>();
    final firstService = _ControlledMarketService([Future.value(initial)]);
    final secondService = _ControlledMarketService([pending.future]);
    final firstController = GlobalMarketContextController(service: firstService);
    final secondController = GlobalMarketContextController(service: secondService);

    await tester.pumpWidget(MaterialApp(home: MarketPage(controller: firstController)));
    await tester.pumpAndSettle();
    expect(find.text('Contexto anterior'), findsOneWidget);

    await tester.pumpWidget(MaterialApp(home: MarketPage(controller: secondController)));
    await tester.pump();
    expect(find.text('Contexto anterior'), findsNothing);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(firstService.calls, 1);
    expect(secondService.calls, 1);

    pending.complete(await _context('Contexto actualizado'));
    await tester.pumpAndSettle();
    expect(find.text('Contexto actualizado'), findsOneWidget);
    expect(find.text('Contexto anterior'), findsNothing);

    await tester.pumpWidget(const SizedBox.shrink());
    firstController.dispose();
    secondController.dispose();
  });

  testWidgets('Market mount invalidates an in-flight request on a reused controller',
      (tester) async {
    final stale = Completer<GlobalMarketContext>();
    final service = _ControlledMarketService([
      stale.future,
      _context('Contexto del montaje vigente'),
    ]);
    final controller = GlobalMarketContextController(service: service);
    addTearDown(controller.dispose);

    unawaited(controller.loadGlobalContext());
    expect(service.calls, 1);
    await tester.pumpWidget(MaterialApp(home: MarketPage(controller: controller)));
    await tester.pumpAndSettle();

    expect(service.calls, 2);
    expect(find.text('Contexto del montaje vigente'), findsOneWidget);
    stale.complete(await _context('Contexto de montaje anterior'));
    await tester.pump();
    expect(find.text('Contexto de montaje anterior'), findsNothing);
    expect(find.text('Contexto del montaje vigente'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('Market controller rebind rejects a prior pending snapshot after new failure',
      (tester) async {
    final first = GlobalMarketContextController(
      service: _ControlledMarketService([
        _context('Mercado de la primera fuente'),
      ]),
    );
    final stale = Completer<GlobalMarketContext>();
    final failedRefresh = Completer<GlobalMarketContext>();
    final secondService = _ControlledMarketService([
      stale.future,
      failedRefresh.future,
    ]);
    final second = GlobalMarketContextController(service: secondService);
    addTearDown(first.dispose);
    addTearDown(second.dispose);

    await tester.pumpWidget(MaterialApp(home: MarketPage(controller: first)));
    await tester.pumpAndSettle();
    expect(find.text('Mercado de la primera fuente'), findsOneWidget);

    unawaited(second.loadGlobalContext());
    expect(secondService.calls, 1);
    await tester.pumpWidget(MaterialApp(home: MarketPage(controller: second)));
    // Attach the controller's error handler before the provider rejects.
    failedRefresh.completeError(const FormatException('invalid market provenance; token=secret-value'));
    await tester.pumpAndSettle();
    expect(secondService.calls, 2);
    expect(find.text('Mercado de la primera fuente'), findsNothing);
    expect(second.context, isNull);
    expect(second.error, 'No se pudo verificar el contexto global del mercado. Reintenta la consulta.');
    expect(find.textContaining('secret-value'), findsNothing);
    expect(
      find.byWidgetPredicate((widget) =>
          widget is Semantics &&
          widget.properties.liveRegion == true &&
          widget.properties.label ==
              'No se pudo actualizar el contexto global del mercado.'),
      findsOneWidget,
    );

    stale.complete(await _context('Snapshot anterior sin autoridad'));
    await tester.pump();
    expect(find.text('Snapshot anterior sin autoridad'), findsNothing);
    expect(second.context, isNull);
    expect(second.error, 'No se pudo verificar el contexto global del mercado. Reintenta la consulta.');
    expect(find.textContaining('secret-value'), findsNothing);
    expect(
      find.byWidgetPredicate((widget) =>
          widget is Semantics &&
          widget.properties.liveRegion == true &&
          widget.properties.label ==
              'No se pudo actualizar el contexto global del mercado.'),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  });

}
