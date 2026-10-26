import 'dart:async';
import 'dart:convert';

import 'package:app/features/dashboard/presentation/pages/dashboard_page.dart';
import 'package:app/features/recommendations/controllers/athena_synthesis_controller.dart';
import 'package:app/features/recommendations/data/datasources/athena_backend_professional_dossier_data_source.dart';
import 'package:app/features/recommendations/data/datasources/athena_backend_recommendation_learning_data_source.dart';
import 'package:app/features/recommendations/data/datasources/athena_backend_recommendation_production_data_source.dart';
import 'package:app/features/recommendations/data/datasources/athena_backend_recommendation_shadow_candidate_data_source.dart';
import 'package:app/features/recommendations/data/datasources/athena_backend_synthesis_data_source.dart';
import 'package:app/features/recommendations/di/recommendation_dependencies.dart';
import 'package:app/features/recommendations/controllers/recommendation_learning_controller.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  Widget synthesisDashboard(RecommendationDependencies dependencies) => MaterialApp(
        home: DashboardPage(
          recommendationDependencies: dependencies,
          renderOperationalPanels: false,
        ),
      );

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
    await tester.pump(const Duration(milliseconds: 400));
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
