import 'dart:async';
import 'dart:convert';

import 'package:app/core/routing/app_routes.dart';
import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/dashboard/presentation/pages/dashboard_page.dart';
import 'package:app/features/recommendations/controllers/athena_synthesis_controller.dart';
import 'package:app/features/recommendations/data/datasources/athena_backend_professional_dossier_data_source.dart';
import 'package:app/features/recommendations/data/datasources/athena_backend_recommendation_learning_data_source.dart';
import 'package:app/features/recommendations/data/datasources/athena_backend_recommendation_production_data_source.dart';
import 'package:app/features/recommendations/data/datasources/athena_backend_recommendation_shadow_candidate_data_source.dart';
import 'package:app/features/recommendations/data/datasources/athena_backend_synthesis_data_source.dart';
import 'package:app/features/recommendations/di/recommendation_dependencies.dart';
import 'package:app/features/recommendations/controllers/recommendation_learning_controller.dart';
import 'package:app/features/dashboard/presentation/widgets/relevant_investors_panel.dart';
import 'package:app/features/investors/models/relevant_investor_activity.dart';
import 'package:app/features/news/models/verified_news_feed.dart';
import 'package:app/features/news/presentation/news_synthesis_controller.dart';
import 'package:app/features/news/presentation/pages/news_page.dart';
import 'package:app/features/news/services/athena_backend_news_synthesis_service.dart';
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
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';


class _UnusedMarketRegionService implements RegionalMarketContextService {
  @override
  Future<RegionalMarketContext> getRegionalContext({
    required MarketRegion region,
  }) async => throw UnimplementedError();
}

class _UnusedMarketUniverse implements MarketUniverseRepository {
  const _UnusedMarketUniverse();

  @override
  Future<List<MarketUniverseAsset>> getUniverse() async => const [];
}

class _UnavailableMarketService extends GlobalMarketDataService {
  _UnavailableMarketService()
      : super(
          regionalMarketContextService: _UnusedMarketRegionService(),
          globalMarketContextService: const GlobalMarketContextService(),
          marketUniverseRepository: const _UnusedMarketUniverse(),
          regionalMarketWeightService: const RegionalMarketWeightService(),
        );

  int calls = 0;

  @override
  Future<GlobalMarketContext> getGlobalContext() async {
    calls++;
    throw StateError('private market provider token=must-not-leak');
  }
}

void main() {

  Widget operationalEpochPanels(
    int owner, int market, int news, int investors, int research, int readiness,
  ) => Column(children: [
    SizedBox(key: Key('dashboard-my-space-$owner'), height: 1),
    SizedBox(key: Key('dashboard-market-$market'), height: 1),
    SizedBox(key: Key('dashboard-news-$news'), height: 1),
    SizedBox(key: Key('dashboard-investors-$investors'), height: 1),
    SizedBox(key: Key('dashboard-recommendations-$research'), height: 1),
    SizedBox(key: Key('dashboard-score-$research'), height: 1),
    SizedBox(key: Key('dashboard-readiness-$readiness'), height: 1),
  ]);

  Widget synthesisDashboard(RecommendationDependencies dependencies) => MaterialApp(
        home: DashboardPage(
          recommendationDependencies: dependencies,
          renderOperationalPanels: false,
        ),
      );


  testWidgets(
      'Dashboard initial mount invalidates an injected synthesis already in flight',
      (tester) async {
    final pending = Completer<http.Response>();
    var requests = 0;
    final stale = _validPayload();
    ((stale['data'] as Map<String, dynamic>)['synthesis']
        as Map<String, dynamic>)['summary'] = 'Síntesis anterior al montaje';
    final fresh = _validPayload();
    ((fresh['data'] as Map<String, dynamic>)['synthesis']
        as Map<String, dynamic>)['summary'] = 'Síntesis del montaje actual';
    final dependencies = _dependencies(AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((_) {
        requests++;
        if (requests == 1) return pending.future;
        return Future.value(http.Response(jsonEncode(fresh), 200,
            headers: {'content-type': 'application/json'}));
      }),
    ));
    addTearDown(dependencies.dispose);

    unawaited(dependencies.synthesisController.loadLatest());
    await tester.pump();
    expect(requests, 1);

    await tester.pumpWidget(synthesisDashboard(dependencies));
    await tester.pumpAndSettle();
    expect(requests, 2);
    expect(find.text('Síntesis del montaje actual'), findsOneWidget);

    pending.complete(http.Response(jsonEncode(stale), 200,
        headers: {'content-type': 'application/json'}));
    await tester.pump();
    expect(find.text('Síntesis anterior al montaje'), findsNothing);
    expect(find.text('Síntesis del montaje actual'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('Dashboard loads latest canonical ATHENA synthesis without cycle hash', (tester) async {
    late Uri requested;
    final client = MockClient((request) async {
      requested = request.url;
      return http.Response(jsonEncode(_validPayload()), 200,
          headers: {'content-type': 'application/json'});
    });
    final synthesisDataSource = AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: client,
    );
    final dependencies = _dependencies(synthesisDataSource);

    await tester.pumpWidget(synthesisDashboard(dependencies));
    await tester.pumpAndSettle();

    expect(requested.path,
        '/api/v1/recommendations/professional-research/athena-synthesis/latest');
    expect(find.byKey(const Key('athena-synthesis-content')), findsOneWidget);
    expect(find.text('Resumen canónico'), findsOneWidget);
    expect(find.text('News verificada'), findsOneWidget);
    expect(find.text('Investors verificado'), findsOneWidget);
    expect(find.text('Fuentes verificadas'), findsOneWidget);
    expect(find.text('https://news.example/item'), findsOneWidget);
    expect(find.text('https://investors.example/filing'), findsOneWidget);
    expect(
      find.byKey(const Key('athena-synthesis-source-refs')),
      findsOneWidget,
    );
    expect(
      find.bySemanticsLabel(
        '2 fuentes HTTPS verificadas vinculadas a la síntesis ATHENA.',
      ),
      findsOneWidget,
    );
    expect(
      find.bySemanticsLabel(
        'Provenance de la síntesis ATHENA: News verificada; Investors verificado; 2 evidencias vinculadas.',
      ),
      findsOneWidget,
    );
    expect(
      find.bySemanticsLabel(
        'Síntesis informativa basada en evidencia verificada. Expone incertidumbres; no garantiza resultados, no ejecuta operaciones y no modifica automáticamente recomendaciones.',
      ),
      findsOneWidget,
    );

    dependencies.dispose();
  });


  testWidgets('Dashboard rebinds ATHENA synthesis when injected dependencies change', (tester) async {
    final oldPayload = _validPayload();
    ((oldPayload['data'] as Map<String, dynamic>)['synthesis']
        as Map<String, dynamic>)['summary'] = 'Síntesis anterior';
    final newPayload = _validPayload();
    ((newPayload['data'] as Map<String, dynamic>)['synthesis']
        as Map<String, dynamic>)['summary'] = 'Síntesis actual';

    final oldDependencies = _dependencies(AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((_) async => http.Response(jsonEncode(oldPayload), 200)),
    ));
    final newDependencies = _dependencies(AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((_) async => http.Response(jsonEncode(newPayload), 200)),
    ));

    await tester.pumpWidget(synthesisDashboard(oldDependencies));
    await tester.pumpAndSettle();
    expect(find.text('Síntesis anterior'), findsOneWidget);

    await tester.pumpWidget(synthesisDashboard(newDependencies));
    await tester.pumpAndSettle();
    expect(find.text('Síntesis actual'), findsOneWidget);
    expect(find.text('Síntesis anterior'), findsNothing);

    oldDependencies.dispose();
    newDependencies.dispose();
  });

  testWidgets('Dashboard does not display an old pending synthesis after source swap', (tester) async {
    final pending = Completer<http.Response>();
    final oldDependencies = _dependencies(AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((_) => pending.future),
    ));
    final newPayload = _validPayload();
    ((newPayload['data'] as Map<String, dynamic>)['synthesis']
        as Map<String, dynamic>)['summary'] = 'Síntesis nueva';
    final newDependencies = _dependencies(AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((_) async => http.Response(jsonEncode(newPayload), 200)),
    ));

    await tester.pumpWidget(synthesisDashboard(oldDependencies));
    await tester.pump();
    await tester.pumpWidget(synthesisDashboard(newDependencies));
    await tester.pumpAndSettle();
    expect(find.text('Síntesis nueva'), findsOneWidget);

    final oldPayload = _validPayload();
    ((oldPayload['data'] as Map<String, dynamic>)['synthesis']
        as Map<String, dynamic>)['summary'] = 'Respuesta obsoleta';
    pending.complete(http.Response(jsonEncode(oldPayload), 200));
    await tester.pump();
    expect(find.text('Síntesis nueva'), findsOneWidget);
    expect(find.text('Respuesta obsoleta'), findsNothing);

    oldDependencies.dispose();
    newDependencies.dispose();
  });


  testWidgets(
      'Dashboard rebinding invalidates an already loading injected synthesis',
      (tester) async {
    final oldDependencies = _dependencies(AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((_) async =>
          http.Response(jsonEncode(_validPayload()), 200)),
    ));
    final pendingPriorMount = Completer<http.Response>();
    var reboundCalls = 0;
    final fresh = _validPayload();
    ((fresh['data'] as Map<String, dynamic>)['synthesis']
        as Map<String, dynamic>)['summary'] = 'Síntesis de la nueva vinculación';
    final stale = _validPayload();
    ((stale['data'] as Map<String, dynamic>)['synthesis']
        as Map<String, dynamic>)['summary'] = 'Síntesis del montaje anterior';
    final reboundDependencies = _dependencies(AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((_) {
        reboundCalls++;
        if (reboundCalls == 1) return pendingPriorMount.future;
        return Future.value(http.Response(jsonEncode(fresh), 200));
      }),
    ));

    await tester.pumpWidget(synthesisDashboard(oldDependencies));
    await tester.pumpAndSettle();
    unawaited(reboundDependencies.synthesisController.loadLatest());
    await tester.pump();
    expect(reboundCalls, 1);

    await tester.pumpWidget(synthesisDashboard(reboundDependencies));
    await tester.pumpAndSettle();
    expect(reboundCalls, 2);
    expect(find.text('Síntesis de la nueva vinculación'), findsOneWidget);
    expect(find.text('Síntesis del montaje anterior'), findsNothing);

    pendingPriorMount.complete(http.Response(jsonEncode(stale), 200));
    await tester.pump();
    expect(find.text('Síntesis de la nueva vinculación'), findsOneWidget);
    expect(find.text('Síntesis del montaje anterior'), findsNothing);
    expect(tester.takeException(), isNull);

    await tester.pumpWidget(const SizedBox.shrink());
    oldDependencies.dispose();
    reboundDependencies.dispose();
  });

  testWidgets('Dashboard rejects ATHENA synthesis that escalates operational authority', (tester) async {
    final payload = _validPayload();
    (payload['data'] as Map<String, dynamic>)['automaticTrading'] = true;
    final client = MockClient((request) async => http.Response(
          jsonEncode(payload),
          200,
          headers: {'content-type': 'application/json'},
        ));
    final synthesisDataSource = AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: client,
    );
    final dependencies = _dependencies(synthesisDataSource);

    await tester.pumpWidget(synthesisDashboard(dependencies));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('athena-synthesis-content')), findsNothing);
    expect(find.text('Resumen canónico'), findsNothing);
    expect(find.byKey(const Key('athena-synthesis-error')), findsOneWidget);
    expect(find.byKey(const Key('athena-synthesis-retry')), findsOneWidget);

    dependencies.dispose();
  });

  testWidgets('Dashboard fails closed when latest ATHENA synthesis is unavailable', (tester) async {
    final client = MockClient((request) async => http.Response(
          jsonEncode({'detail': 'No existe ninguna ATHENA synthesis persistida.'}),
          404,
          headers: {'content-type': 'application/json'},
        ));
    final synthesisDataSource = AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: client,
    );
    final dependencies = _dependencies(synthesisDataSource);

    await tester.pumpWidget(synthesisDashboard(dependencies));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('athena-synthesis-content')), findsNothing);
    expect(find.text('Resumen canónico'), findsNothing);
    expect(find.byKey(const Key('athena-synthesis-error')), findsOneWidget);
    expect(find.byKey(const Key('athena-synthesis-retry')), findsOneWidget);

    dependencies.dispose();
  });

  testWidgets('Dashboard retry reloads latest ATHENA synthesis after transient failure', (tester) async {
    var requests = 0;
    final client = MockClient((request) async {
      requests += 1;
      if (requests == 1) {
        return http.Response(
          jsonEncode({'detail': 'Servicio temporalmente no disponible.'}),
          503,
          headers: {'content-type': 'application/json'},
        );
      }
      return http.Response(jsonEncode(_validPayload()), 200,
          headers: {'content-type': 'application/json'});
    });
    final synthesisDataSource = AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: client,
    );
    final dependencies = _dependencies(synthesisDataSource);

    await tester.pumpWidget(synthesisDashboard(dependencies));
    await tester.pumpAndSettle();

    expect(requests, 1);
    expect(find.byKey(const Key('athena-synthesis-content')), findsNothing);
    expect(find.byKey(const Key('athena-synthesis-retry')), findsOneWidget);

    await tester.tap(find.byKey(const Key('athena-synthesis-retry')));
    await tester.pumpAndSettle();

    expect(requests, 2);
    expect(find.byKey(const Key('athena-synthesis-error')), findsNothing);
    expect(find.byKey(const Key('athena-synthesis-content')), findsOneWidget);
    expect(find.text('Resumen canónico'), findsOneWidget);

    dependencies.dispose();
  });

  testWidgets('Market and News returns refresh canonical synthesis fail-closed',
      (tester) async {
    var requests = 0;
    final source = AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((_) async {
        requests++;
        if (requests == 2) return http.Response('{"detail":"unavailable"}', 503);
        final payload = _validPayload();
        ((payload['data'] as Map<String, dynamic>)['synthesis']
            as Map<String, dynamic>)['summary'] =
            requests == 1 ? 'Síntesis anterior' : 'Síntesis renovada';
        return http.Response(jsonEncode(payload), 200,
            headers: {'content-type': 'application/json'});
      }),
    );
    final dependencies = _dependencies(source);
    addTearDown(dependencies.dispose);
    await tester.pumpWidget(MaterialApp(
      home: DashboardPage(
        recommendationDependencies: dependencies,
        renderOperationalPanels: false,
      ),
      onGenerateRoute: (settings) => MaterialPageRoute<void>(
        settings: settings,
        builder: (_) => Scaffold(body: Text('Abierta: ${settings.name}')),
      ),
    ));
    await tester.pumpAndSettle();
    expect(requests, 1);
    expect(find.text('Síntesis anterior'), findsOneWidget);

    await tester.tap(find.byTooltip('Mercado'));
    await tester.pumpAndSettle();
    Navigator.of(tester.element(find.text('Abierta: /market'))).pop();
    await tester.pumpAndSettle();
    expect(requests, 2);
    expect(find.text('Síntesis anterior'), findsNothing);
    expect(find.byKey(const Key('athena-synthesis-error')), findsOneWidget);

    await tester.tap(find.byTooltip('Noticias'));
    await tester.pumpAndSettle();
    Navigator.of(tester.element(find.text('Abierta: /news'))).pop();
    await tester.pumpAndSettle();
    expect(requests, 3);
    expect(find.byKey(const Key('athena-synthesis-error')), findsNothing);
    expect(find.text('Síntesis renovada'), findsOneWidget);
  });

  testWidgets('late Market response cannot overwrite refreshed News synthesis',
      (tester) async {
    final delayedMarket = Completer<http.Response>();
    var requests = 0;
    final source = AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((_) {
        requests++;
        if (requests == 2) return delayedMarket.future;
        final payload = _validPayload();
        ((payload['data'] as Map<String, dynamic>)['synthesis']
            as Map<String, dynamic>)['summary'] =
            requests == 1 ? 'Síntesis inicial' : 'Síntesis de noticias';
        return Future.value(http.Response(jsonEncode(payload), 200,
            headers: {'content-type': 'application/json'}));
      }),
    );
    final dependencies = _dependencies(source);
    addTearDown(dependencies.dispose);
    await tester.pumpWidget(MaterialApp(
      home: DashboardPage(
        recommendationDependencies: dependencies,
        renderOperationalPanels: false,
      ),
      onGenerateRoute: (settings) => MaterialPageRoute<void>(
        settings: settings,
        builder: (_) => Scaffold(body: Text('Abierta: ${settings.name}')),
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Síntesis inicial'), findsOneWidget);

    await tester.tap(find.byTooltip('Mercado'));
    await tester.pumpAndSettle();
    Navigator.of(tester.element(find.text('Abierta: /market'))).pop();
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pump();
    expect(requests, 2);
    expect(find.text('Síntesis inicial'), findsNothing);

    await tester.tap(find.byTooltip('Noticias'));
    // Let the named route finish its push before looking up its context.
    // The pending Market request belongs to the now-offstage Dashboard.
    await tester.pumpAndSettle();
    expect(find.text('Abierta: /news'), findsOneWidget);
    Navigator.of(tester.element(find.text('Abierta: /news'))).pop();
    await tester.pumpAndSettle();
    expect(requests, 3);
    expect(find.text('Síntesis de noticias'), findsOneWidget);

    final oldPayload = _validPayload();
    ((oldPayload['data'] as Map<String, dynamic>)['synthesis']
        as Map<String, dynamic>)['summary'] = 'Respuesta tardía';
    delayedMarket.complete(http.Response(jsonEncode(oldPayload), 200,
        headers: {'content-type': 'application/json'}));
    await tester.pump();
    expect(find.text('Respuesta tardía'), findsNothing);
    expect(find.text('Síntesis de noticias'), findsOneWidget);
  });

  testWidgets('Dashboard manual refresh clears stale evidence and recovers on retry',
      (tester) async {
    var requests = 0;
    final source = AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((_) async {
        requests++;
        if (requests == 2) return http.Response('{"detail":"unavailable"}', 503);
        final payload = _validPayload();
        ((payload['data'] as Map<String, dynamic>)['synthesis']
            as Map<String, dynamic>)['summary'] =
            requests == 1 ? 'Evidencia anterior' : 'Evidencia renovada';
        return http.Response(jsonEncode(payload), 200,
            headers: {'content-type': 'application/json'});
      }),
    );
    final dependencies = _dependencies(source);
    addTearDown(dependencies.dispose);
    await tester.pumpWidget(synthesisDashboard(dependencies));
    await tester.pumpAndSettle();
    expect(find.text('Evidencia anterior'), findsOneWidget);

    await tester.tap(find.byKey(const Key('dashboard-refresh-all')));
    await tester.pumpAndSettle();
    expect(requests, 2);
    expect(find.text('Evidencia anterior'), findsNothing);
    expect(find.byKey(const Key('athena-synthesis-error')), findsOneWidget);

    await tester.tap(find.byKey(const Key('athena-synthesis-retry')));
    await tester.pumpAndSettle();
    expect(requests, 3);
    expect(find.text('Evidencia renovada'), findsOneWidget);
    expect(find.byKey(const Key('athena-synthesis-error')), findsNothing);
  });

  testWidgets('Dashboard repeated manual refresh ignores late older synthesis',
      (tester) async {
    final pending = Completer<http.Response>();
    var requests = 0;
    final source = AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((_) {
        requests++;
        if (requests == 2) return pending.future;
        final payload = _validPayload();
        ((payload['data'] as Map<String, dynamic>)['synthesis']
            as Map<String, dynamic>)['summary'] =
            requests == 1 ? 'Evidencia inicial' : 'Evidencia más reciente';
        return Future.value(http.Response(jsonEncode(payload), 200,
            headers: {'content-type': 'application/json'}));
      }),
    );
    final dependencies = _dependencies(source);
    addTearDown(dependencies.dispose);
    await tester.pumpWidget(synthesisDashboard(dependencies));
    await tester.pumpAndSettle();
    expect(find.text('Evidencia inicial'), findsOneWidget);

    await tester.tap(find.byKey(const Key('dashboard-refresh-all')));
    await tester.pump();
    expect(requests, 2);
    expect(find.text('Evidencia inicial'), findsNothing);

    await tester.tap(find.byKey(const Key('dashboard-refresh-all')));
    await tester.pumpAndSettle();
    expect(requests, 3);
    expect(find.text('Evidencia más reciente'), findsOneWidget);

    final old = _validPayload();
    ((old['data'] as Map<String, dynamic>)['synthesis']
        as Map<String, dynamic>)['summary'] = 'Respuesta caducada';
    pending.complete(http.Response(jsonEncode(old), 200,
        headers: {'content-type': 'application/json'}));
    await tester.pump();
    expect(find.text('Respuesta caducada'), findsNothing);
    expect(find.text('Evidencia más reciente'), findsOneWidget);
  });


  AuthAccount ownerAccount(int id) => AuthAccount(
    id: id,
    email: 'owner-$id@example.com',
    displayName: 'Owner $id',
    isActive: true,
    createdAt: DateTime.utc(2026, 10, 1),
    updatedAt: DateTime.utc(2026, 10, 1),
  );

  testWidgets(
      'Dashboard invalidates owner, research and readiness when authenticated authority changes',
      (tester) async {
    final session = AuthSession.instance;
    session.clear();
    addTearDown(session.clear);
    final dependencies = _dependencies(AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((_) async => http.Response(
        jsonEncode(_validPayload()), 200,
        headers: {'content-type': 'application/json'},
      )),
    ));
    addTearDown(dependencies.dispose);
    await tester.pumpWidget(MaterialApp(
      home: DashboardPage(
        recommendationDependencies: dependencies,
        operationalPanelsBuilder: operationalEpochPanels,
      ),
    ));
    await tester.pump();
    expect(find.byKey(const Key('dashboard-my-space-0')), findsOneWidget);

    session.establish(accessToken: 'same-token', account: ownerAccount(1));
    await tester.pump();
    for (final panel in const ['my-space', 'recommendations', 'score', 'readiness']) {
      expect(find.byKey(Key('dashboard-$panel-1')), findsOneWidget,
          reason: '$panel must be recreated for the authenticated owner');
    }
    expect(find.byKey(const Key('dashboard-market-0')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-news-0')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-investors-0')), findsOneWidget);

    // Credential text equality does not confer the previous owner's authority.
    session.establish(accessToken: 'same-token', account: ownerAccount(2));
    await tester.pump();
    for (final panel in const ['my-space', 'recommendations', 'score', 'readiness']) {
      expect(find.byKey(Key('dashboard-$panel-1')), findsNothing);
      expect(find.byKey(Key('dashboard-$panel-2')), findsOneWidget);
    }
    expect(find.byKey(const Key('dashboard-market-0')), findsOneWidget);

    session.clear();
    await tester.pump();
    expect(find.byKey(const Key('dashboard-my-space-2')), findsNothing);
    expect(find.byKey(const Key('dashboard-my-space-3')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-recommendations-3')), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets(
      'Dashboard ignores pending synthesis from a previous owner after a token-reused switch',
      (tester) async {
    final session = AuthSession.instance;
    session.clear();
    addTearDown(session.clear);
    session.establish(accessToken: 'same-token', account: ownerAccount(1));
    final oldOwnerResponse = Completer<http.Response>();
    var requests = 0;
    final dependencies = _dependencies(AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((_) {
        requests++;
        if (requests == 1) return oldOwnerResponse.future;
        final payload = _validPayload();
        ((payload['data'] as Map<String, dynamic>)['synthesis']
            as Map<String, dynamic>)['summary'] = 'Síntesis posterior al cambio';
        return Future.value(http.Response(jsonEncode(payload), 200,
            headers: {'content-type': 'application/json'}));
      }),
    ));
    addTearDown(dependencies.dispose);
    await tester.pumpWidget(synthesisDashboard(dependencies));
    await tester.pump();
    expect(requests, 1);

    session.establish(accessToken: 'same-token', account: ownerAccount(2));
    await tester.pumpAndSettle();
    expect(requests, 2);
    expect(find.text('Síntesis posterior al cambio'), findsOneWidget);

    final oldPayload = _validPayload();
    ((oldPayload['data'] as Map<String, dynamic>)['synthesis']
        as Map<String, dynamic>)['summary'] = 'Síntesis de otro propietario';
    oldOwnerResponse.complete(http.Response(jsonEncode(oldPayload), 200,
        headers: {'content-type': 'application/json'}));
    await tester.pump();
    expect(find.text('Síntesis de otro propietario'), findsNothing);
    expect(find.text('Síntesis posterior al cambio'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('Dashboard full refresh rebinds every operational and research projection',
      (tester) async {
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final dependencies = _dependencies(AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((_) async => http.Response(
        jsonEncode(_validPayload()), 200,
        headers: {'content-type': 'application/json'},
      )),
    ));
    addTearDown(dependencies.dispose);
    await tester.pumpWidget(MaterialApp(
      home: DashboardPage(
        recommendationDependencies: dependencies,
        operationalPanelsBuilder: operationalEpochPanels,
      ),
    ));
    await tester.pump();

    for (final panel in const [
      'readiness', 'recommendations', 'score', 'market', 'news',
      'investors', 'my-space',
    ]) {
      expect(find.byKey(Key('dashboard-$panel-0')), findsOneWidget,
          reason: '$panel must exist before refresh');
    }

    await tester.tap(find.byKey(const Key('dashboard-refresh-all')));
    await tester.pump();
    for (final panel in const [
      'readiness', 'recommendations', 'score', 'market', 'news',
      'investors', 'my-space',
    ]) {
      expect(find.byKey(Key('dashboard-$panel-0')), findsNothing);
      expect(find.byKey(Key('dashboard-$panel-1')), findsOneWidget,
          reason: '$panel must be recreated from its evidence source');
    }

    tester.view.physicalSize = const Size(500, 900);
    await tester.pump();
    expect(find.byKey(const Key('dashboard-recommendations-1')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-score-1')), findsOneWidget);
  });


  testWidgets(
      'Profile and Portfolio returns refresh owner research and readiness together',
      (tester) async {
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final dependencies = _dependencies(AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((_) async => http.Response(
        jsonEncode(_validPayload()), 200,
        headers: {'content-type': 'application/json'},
      )),
    ));
    addTearDown(dependencies.dispose);
    await tester.pumpWidget(MaterialApp(
      home: DashboardPage(
        recommendationDependencies: dependencies,
        operationalPanelsBuilder: operationalEpochPanels,
      ),
      onGenerateRoute: (settings) => MaterialPageRoute<void>(
        settings: settings,
        builder: (_) => Scaffold(body: Text('Abierta: ${settings.name}')),
      ),
    ));
    await tester.pump();

    for (final (route, label, epoch) in [
      (AppRoutes.profile, 'Perfil', 1),
      (AppRoutes.portfolio, 'Cartera', 2),
    ]) {
      await tester.tap(find.byTooltip(label));
      await tester.pumpAndSettle();
      Navigator.of(tester.element(find.text('Abierta: $route'))).pop();
      await tester.pump();
      expect(find.byKey(Key('dashboard-my-space-$epoch')), findsOneWidget);
      expect(find.byKey(Key('dashboard-recommendations-$epoch')), findsOneWidget);
      expect(find.byKey(Key('dashboard-score-$epoch')), findsOneWidget);
      expect(find.byKey(Key('dashboard-readiness-$epoch')), findsOneWidget);
      expect(find.byKey(const Key('dashboard-market-0')), findsOneWidget);
      expect(find.byKey(const Key('dashboard-news-0')), findsOneWidget);
      expect(find.byKey(const Key('dashboard-investors-0')), findsOneWidget);
    }
  });

  testWidgets(
      'Profile and Portfolio returns invalidate old ATHENA responses, fail closed and recover selectively',
      (tester) async {
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final pendingProfile = Completer<http.Response>();
    var requests = 0;
    http.Response verifiedResponse(String summary) {
      final payload = _validPayload();
      ((payload['data'] as Map<String, dynamic>)['synthesis']
          as Map<String, dynamic>)['summary'] = summary;
      return http.Response(jsonEncode(payload), 200,
          headers: {'content-type': 'application/json'});
    }

    final dependencies = _dependencies(AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((_) {
        requests++;
        if (requests == 2) return pendingProfile.future;
        if (requests == 3) {
          return Future.value(http.Response('{"detail":"unavailable"}', 503));
        }
        return Future.value(verifiedResponse('Síntesis verificada $requests'));
      }),
    ));
    addTearDown(dependencies.dispose);

    await tester.pumpWidget(MaterialApp(
      home: DashboardPage(
        recommendationDependencies: dependencies,
        operationalPanelsBuilder: operationalEpochPanels,
      ),
      onGenerateRoute: (settings) => MaterialPageRoute<void>(
        settings: settings,
        builder: (_) => Scaffold(body: Text('Abierta: ${settings.name}')),
      ),
    ));
    await tester.pumpAndSettle();
    expect(requests, 1);
    expect(find.text('Síntesis verificada 1'), findsOneWidget);

    await tester.tap(find.byTooltip('Perfil'));
    await tester.pumpAndSettle();
    Navigator.of(tester.element(find.text('Abierta: /profile'))).pop();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 350));
    expect(requests, 2);
    expect(find.text('Síntesis verificada 1'), findsNothing);

    await tester.tap(find.byTooltip('Cartera'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('Abierta: /portfolio'), findsOneWidget);
    Navigator.of(tester.element(find.text('Abierta: /portfolio'))).pop();
    // The failed request settles immediately, so finish the route's reverse
    // transition before tapping the Dashboard retry control.
    await tester.pumpAndSettle();
    expect(requests, 3);
    expect(find.byKey(const Key('athena-synthesis-error')), findsOneWidget);
    expect(find.text('Síntesis verificada 1'), findsNothing);

    pendingProfile.complete(verifiedResponse('Síntesis obsoleta de Perfil'));
    await tester.pump();
    expect(find.text('Síntesis obsoleta de Perfil'), findsNothing);
    expect(find.byKey(const Key('athena-synthesis-error')), findsOneWidget);

    await tester.tap(find.byKey(const Key('athena-synthesis-retry')));
    await tester.pumpAndSettle();
    expect(requests, 4);
    expect(find.text('Síntesis verificada 4'), findsOneWidget);
    expect(find.byKey(const Key('athena-synthesis-error')), findsNothing);
    expect(find.byKey(const Key('dashboard-my-space-2')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-recommendations-2')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-readiness-2')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-market-0')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-news-0')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-investors-0')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('Market and News return refresh research/readiness but preserve owner scope',
      (tester) async {
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final dependencies = _dependencies(AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((_) async => http.Response(
        jsonEncode(_validPayload()), 200,
        headers: {'content-type': 'application/json'},
      )),
    ));
    addTearDown(dependencies.dispose);
    await tester.pumpWidget(MaterialApp(
      home: DashboardPage(
        recommendationDependencies: dependencies,
        operationalPanelsBuilder: operationalEpochPanels,
      ),
      onGenerateRoute: (settings) => MaterialPageRoute<void>(
        settings: settings,
        builder: (_) => Scaffold(body: Text('Abierta: ${settings.name}')),
      ),
    ));
    await tester.pump();
    await tester.tap(find.byTooltip('Mercado'));
    await tester.pumpAndSettle();
    Navigator.of(tester.element(find.text('Abierta: /market'))).pop();
    await tester.pump();
    expect(find.byKey(const Key('dashboard-recommendations-1')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-score-1')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-readiness-1')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-market-1')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-news-0')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-my-space-0')), findsOneWidget);

    await tester.tap(find.byTooltip('Noticias'));
    await tester.pumpAndSettle();
    Navigator.of(tester.element(find.text('Abierta: /news'))).pop();
    await tester.pump();
    expect(find.byKey(const Key('dashboard-recommendations-2')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-score-2')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-readiness-2')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-market-1')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-news-1')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-my-space-0')), findsOneWidget);
  });


  testWidgets('Dashboard ATHENA hides provider diagnostics and recovers on retry',
      (tester) async {
    var calls = 0;
    final source = AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((_) {
        calls++;
        if (calls == 1) {
          return Future<http.Response>.error(
            StateError('provider URL contains token=secret-value'),
          );
        }
        return Future.value(http.Response(
          jsonEncode(_validPayload()),
          200,
          headers: {'content-type': 'application/json'},
        ));
      }),
    );
    final dependencies = _dependencies(source);
    addTearDown(dependencies.dispose);

    await tester.pumpWidget(synthesisDashboard(dependencies));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('athena-synthesis-error')), findsOneWidget);
    expect(find.textContaining('secret-value'), findsNothing);
    expect(find.textContaining('No se pudo verificar'), findsWidgets);

    await tester.tap(find.byKey(const Key('athena-synthesis-retry')));
    await tester.pumpAndSettle();
    expect(calls, 2);
    expect(find.byKey(const Key('athena-synthesis-error')), findsNothing);
    expect(find.byKey(const Key('athena-synthesis-content')), findsOneWidget);
  });

  testWidgets(
      'Dashboard Market News Investors ATHENA route lifecycle keeps selective evidence and fail-closed boundaries',
      (tester) async {
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var athenaRequests = 0;
    var investorRequests = 0;
    var newsSynthesisRequests = 0;
    var feedRequests = 0;
    final marketService = _UnavailableMarketService();
    final marketController = GlobalMarketContextController(service: marketService);
    addTearDown(marketController.dispose);
    final synthesisSource = AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((_) async {
        athenaRequests++;
        if (athenaRequests == 2) {
          return http.Response('{"detail":"unavailable"}', 503);
        }
        final payload = _validPayload();
        ((payload['data'] as Map<String, dynamic>)['synthesis']
            as Map<String, dynamic>)['summary'] =
            'ATHENA evidencia vigente $athenaRequests';
        return http.Response(jsonEncode(payload), 200,
            headers: {'content-type': 'application/json'});
      }),
    );
    final dependencies = _dependencies(synthesisSource);
    addTearDown(dependencies.dispose);
    final newsService = AthenaBackendNewsSynthesisService(
      baseUrl: 'https://athena.example',
      client: MockClient((_) async {
        newsSynthesisRequests++;
        return http.Response('{"detail":"unavailable"}', 503);
      }),
    );
    final newsController = NewsSynthesisController(service: newsService);
    addTearDown(newsController.dispose);
    addTearDown(newsService.dispose);

    Future<RelevantInvestorActivity> investorLoader(String cik) async {
      investorRequests++;
      return RelevantInvestorActivity(
        cik: cik,
        form: '13F-HR',
        accessionNumber: '0000123456-26-000001',
        positionDate: DateTime.utc(2026, 6, 30),
        filingDate: DateTime.utc(2026, 8, 14),
        publicationDateTime: DateTime.utc(2026, 8, 14, 20),
        retrievedAt: DateTime.utc(2026, 9, 4, 20),
        sourceUrl: 'https://www.sec.gov/Archives/edgar/data/123456/filing.xml',
        sourceProvider: 'SEC EDGAR',
        valueUnit: 'thousands_usd_as_reported_by_sec_13f',
        holdings: const [],
      );
    }

    Future<VerifiedNewsFeed> newsLoader(int limit) async {
      feedRequests++;
      return VerifiedNewsFeed(
        query: 'mercado',
        sourceProvider: 'google_news_rss',
        retrievedAt: DateTime.utc(2026, 9, 4, 20),
        items: [
          VerifiedNewsItem(
            title: 'Noticia verificable independiente',
            publisher: 'Publicador verificado',
            publisherUrl: 'https://example.com',
            articleUrl: 'https://example.com/noticia',
            publishedAt: DateTime.utc(2026, 9, 4, 19),
            retrievedAt: DateTime.utc(2026, 9, 4, 20),
            sourceProvider: 'google_news_rss',
          ),
        ],
      );
    }

    await tester.pumpWidget(MaterialApp(
      home: DashboardPage(
        recommendationDependencies: dependencies,
        operationalPanelsBuilder:
            (owner, market, news, investors, research, readiness) => Column(
          children: [
            operationalEpochPanels(
                owner, market, news, investors, research, readiness),
            SizedBox(
              height: 340,
              child: RelevantInvestorsPanel(
                key: ValueKey('investors-epoch-$investors'),
                configuredCiks: const ['123456'],
                loader: investorLoader,
              ),
            ),
          ],
        ),
      ),
      onGenerateRoute: (settings) {
        if (settings.name == AppRoutes.news) {
          return MaterialPageRoute<void>(
            settings: settings,
            builder: (_) => NewsPage(
              synthesisController: newsController,
              feedLoader: newsLoader,
            ),
          );
        }
        if (settings.name == AppRoutes.market) {
          return MaterialPageRoute<void>(
            settings: settings,
            builder: (_) => MarketPage(controller: marketController),
          );
        }
        return null;
      },
    ));
    await tester.pumpAndSettle();
    expect(athenaRequests, 1);
    expect(investorRequests, 1);
    expect(find.text('ATHENA evidencia vigente 1'), findsOneWidget);
    expect(find.textContaining('CIK 123456'), findsOneWidget);
    expect(find.byKey(const Key('dashboard-investors-0')), findsOneWidget);
    expect(
      find.bySemanticsLabel(
        'Evidencia institucional point-in-time de SEC 13F. Es informativa y separada: no altera el score ATHENA, no genera recomendaciones y no ejecuta órdenes.',
      ),
      findsOneWidget,
    );

    await tester.tap(find.byTooltip('Mercado'));
    await tester.pumpAndSettle();
    expect(marketService.calls, 1);
    expect(find.text('MERCADO'), findsOneWidget);
    expect(find.byKey(const Key('market-information-boundary')), findsOneWidget);
    expect(marketController.error,
        'No se pudo verificar el contexto global del mercado. Reintenta la consulta.');
    expect(
      find.textContaining('No se pudo verificar el contexto global del mercado.'),
      findsOneWidget,
    );
    expect(find.textContaining('must-not-leak'), findsNothing);
    Navigator.of(tester.element(find.text('MERCADO'))).pop();
    await tester.pumpAndSettle();
    expect(athenaRequests, 2);
    expect(find.text('ATHENA evidencia vigente 1'), findsNothing);
    expect(find.byKey(const Key('athena-synthesis-error')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-market-1')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-news-0')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-investors-0')), findsOneWidget);
    expect(investorRequests, 1);

    await tester.tap(find.byTooltip('Noticias'));
    await tester.pumpAndSettle();
    expect(newsSynthesisRequests, 1);
    expect(feedRequests, 1);
    expect(find.text('Noticia verificable independiente'), findsOneWidget);
    expect(find.text('https://example.com/noticia'), findsOneWidget);
    expect(find.text('ANÁLISIS ATHENA DE NOTICIAS'), findsNothing);
    expect(find.text('Reintentar'), findsOneWidget);
    expect(
      find.bySemanticsLabel('Noticias verificadas no disponibles.'),
      findsNothing,
    );
    Navigator.of(tester.element(find.byKey(const Key('news-page-heading')))).pop();
    await tester.pumpAndSettle();

    expect(athenaRequests, 3);
    expect(find.text('ATHENA evidencia vigente 3'), findsOneWidget);
    expect(find.byKey(const Key('dashboard-market-1')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-news-1')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-investors-0')), findsOneWidget);
    expect(investorRequests, 1);

    await tester.tap(find.byKey(const Key('dashboard-refresh-all')));
    await tester.pumpAndSettle();
    expect(athenaRequests, 4);
    expect(investorRequests, 2);
    expect(find.text('ATHENA evidencia vigente 4'), findsOneWidget);
    expect(find.byKey(const Key('dashboard-market-2')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-news-2')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-investors-1')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-my-space-1')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });


  testWidgets(
      'Dashboard rejects a late Market synthesis after News navigation and preserves independent SEC evidence',
      (tester) async {
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final pendingMarketReturn = Completer<http.Response>();
    var athenaRequests = 0;
    var investorRequests = 0;
    var newsFeedRequests = 0;
    final source = AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((_) {
        athenaRequests++;
        if (athenaRequests == 2) return pendingMarketReturn.future;
        final payload = _validPayload();
        ((payload['data'] as Map<String, dynamic>)['synthesis']
            as Map<String, dynamic>)['summary'] =
            'ATHENA verificada $athenaRequests';
        return Future.value(http.Response(jsonEncode(payload), 200,
            headers: {'content-type': 'application/json'}));
      }),
    );
    final dependencies = _dependencies(source);
    addTearDown(dependencies.dispose);
    final marketController = GlobalMarketContextController(
      service: _UnavailableMarketService(),
    );
    addTearDown(marketController.dispose);
    final newsService = AthenaBackendNewsSynthesisService(
      baseUrl: 'https://athena.example',
      client: MockClient((_) async => http.Response('{"detail":"unavailable"}', 503)),
    );
    final newsController = NewsSynthesisController(service: newsService);
    addTearDown(newsController.dispose);
    addTearDown(newsService.dispose);

    Future<RelevantInvestorActivity> investorLoader(String cik) async {
      investorRequests++;
      return RelevantInvestorActivity(
        cik: cik,
        form: '13F-HR',
        accessionNumber: '0000123456-26-000001',
        positionDate: DateTime.utc(2026, 6, 30),
        filingDate: DateTime.utc(2026, 8, 14),
        publicationDateTime: DateTime.utc(2026, 8, 14, 20),
        retrievedAt: DateTime.utc(2026, 9, 4, 20),
        sourceUrl: 'https://www.sec.gov/Archives/edgar/data/123456/filing.xml',
        sourceProvider: 'SEC EDGAR',
        valueUnit: 'thousands_usd_as_reported_by_sec_13f',
        holdings: const [],
      );
    }

    Future<VerifiedNewsFeed> feedLoader(int limit) async {
      newsFeedRequests++;
      return VerifiedNewsFeed(
        query: 'mercado',
        sourceProvider: 'google_news_rss',
        retrievedAt: DateTime.utc(2026, 9, 4, 20),
        items: [
          VerifiedNewsItem(
            title: 'Feed independiente durante síntesis pendiente',
            publisher: 'Fuente verificada',
            publisherUrl: 'https://example.com',
            articleUrl: 'https://example.com/news',
            publishedAt: DateTime.utc(2026, 9, 4, 19),
            retrievedAt: DateTime.utc(2026, 9, 4, 20),
            sourceProvider: 'google_news_rss',
          ),
        ],
      );
    }

    await tester.pumpWidget(MaterialApp(
      home: DashboardPage(
        recommendationDependencies: dependencies,
        operationalPanelsBuilder:
            (owner, market, news, investors, research, readiness) => Column(
          children: [
            operationalEpochPanels(
                owner, market, news, investors, research, readiness),
            SizedBox(
              height: 340,
              child: RelevantInvestorsPanel(
                key: ValueKey('investors-epoch-$investors'),
                configuredCiks: const ['123456'],
                loader: investorLoader,
              ),
            ),
          ],
        ),
      ),
      onGenerateRoute: (settings) {
        if (settings.name == AppRoutes.market) {
          return MaterialPageRoute<void>(
            settings: settings,
            builder: (_) => MarketPage(controller: marketController),
          );
        }
        if (settings.name == AppRoutes.news) {
          return MaterialPageRoute<void>(
            settings: settings,
            builder: (_) => NewsPage(
              synthesisController: newsController,
              feedLoader: feedLoader,
            ),
          );
        }
        return null;
      },
    ));
    await tester.pumpAndSettle();
    expect(athenaRequests, 1);
    expect(investorRequests, 1);
    expect(find.text('ATHENA verificada 1'), findsOneWidget);

    await tester.tap(find.byTooltip('Mercado'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('market-information-boundary')), findsOneWidget);
    Navigator.of(tester.element(find.text('MERCADO'))).pop();
    // The Market-triggered ATHENA request intentionally remains pending:
    // pumpAndSettle would wait forever on its loading indicator.
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(athenaRequests, 2);
    expect(find.text('ATHENA verificada 1'), findsNothing);
    expect(find.byKey(const Key('dashboard-market-1')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-news-0')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-investors-0')), findsOneWidget);

    // Leave the Market-triggered synthesis unresolved while visiting News.
    await tester.tap(find.byTooltip('Noticias'));
    await tester.pumpAndSettle();
    expect(newsFeedRequests, 1);
    expect(find.text('Feed independiente durante síntesis pendiente'),
        findsOneWidget);
    expect(find.text('https://example.com/news'), findsOneWidget);
    expect(find.byKey(const Key('news-page-heading')), findsOneWidget);
    Navigator.of(tester.element(find.byKey(const Key('news-page-heading')))).pop();
    await tester.pumpAndSettle();
    expect(athenaRequests, 3);
    expect(find.text('ATHENA verificada 3'), findsOneWidget);
    expect(find.byKey(const Key('dashboard-market-1')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-news-1')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-investors-0')), findsOneWidget);
    expect(investorRequests, 1);

    final stale = _validPayload();
    ((stale['data'] as Map<String, dynamic>)['synthesis']
        as Map<String, dynamic>)['summary'] =
        'ATHENA obsoleta del retorno de Mercado';
    pendingMarketReturn.complete(http.Response(jsonEncode(stale), 200,
        headers: {'content-type': 'application/json'}));
    await tester.pump();
    expect(find.text('ATHENA obsoleta del retorno de Mercado'), findsNothing);
    expect(find.text('ATHENA verificada 3'), findsOneWidget);
    expect(investorRequests, 1);

    await tester.tap(find.byKey(const Key('dashboard-refresh-all')));
    await tester.pumpAndSettle();
    expect(athenaRequests, 4);
    expect(investorRequests, 2);
    expect(find.text('ATHENA verificada 4'), findsOneWidget);
    expect(find.byKey(const Key('dashboard-market-2')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-news-2')), findsOneWidget);
    expect(find.byKey(const Key('dashboard-investors-1')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

}

RecommendationDependencies _dependencies(
    AthenaBackendSynthesisDataSource synthesisDataSource) {
  const baseUrl = 'https://athena.example';
  final ancillaryClient = MockClient((request) async => http.Response(
        jsonEncode({'detail': 'Not part of synthesis wiring acceptance.'}),
        404,
        headers: {'content-type': 'application/json'},
      ));
  final learning = AthenaBackendRecommendationLearningDataSource(
    baseUrl: baseUrl,
    client: ancillaryClient,
  );
  final shadow = AthenaBackendRecommendationShadowCandidateDataSource(
    baseUrl: baseUrl,
    client: ancillaryClient,
  );
  final production = AthenaBackendRecommendationProductionDataSource(
    baseUrl: baseUrl,
    client: ancillaryClient,
  );
  final dossier = AthenaBackendProfessionalDossierDataSource(
    baseUrl: baseUrl,
    client: ancillaryClient,
  );
  return RecommendationDependencies(
    learningDataSource: learning,
    shadowCandidateDataSource: shadow,
    productionDataSource: production,
    professionalDossierDataSource: dossier,
    synthesisDataSource: synthesisDataSource,
    learningController: RecommendationLearningController(provider: learning),
    synthesisController: AthenaSynthesisController(dataSource: synthesisDataSource),
  );
}

Map<String, dynamic> _validPayload() {
  const fingerprint =
      'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
  const assessmentFingerprint =
      'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
  return {
    'data': {
      'artifactBindingVerified': true,
      'presentationOnly': true,
      'recommendationInfluence': false,
      'automaticTrading': false,
      'synthesis': {
        'inputFingerprint': fingerprint,
        'summary': 'Resumen canónico',
        'rationale': 'Razonamiento trazable',
        'uncertainties': ['Riesgo macro'],
        'evidenceIds': ['news-1', 'investors-1'],
        'recommendationInfluence': false,
        'automaticTrading': false,
      },
      'provenance': {
        'inputFingerprint': fingerprint,
        'news': {
          'artifactHash': fingerprint,
          'artifactType': 'canonical_news_synthesis',
          'userFacingTraceability': true,
          'recommendationInfluence': false,
          'automaticTrading': false,
          'assessmentBindings': [
            {
              'evidenceId': 'news-1',
              'assessmentFingerprint': assessmentFingerprint,
              'sourceRef': 'https://news.example/item',
            }
          ],
        },
        'investors': {
          'artifactHash': fingerprint,
          'artifactType': 'canonical_investors_synthesis',
          'userFacingTraceability': true,
          'recommendationInfluence': false,
          'automaticTrading': false,
          'assessmentBindings': [
            {
              'evidenceId': 'investors-1',
              'assessmentFingerprint': assessmentFingerprint,
              'sourceRef': 'https://investors.example/filing',
            }
          ],
        },
      },
    },
  };
}
