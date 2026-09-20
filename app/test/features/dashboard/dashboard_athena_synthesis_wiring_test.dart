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

    await tester.pumpWidget(MaterialApp(
      home: DashboardPage(recommendationDependencies: dependencies),
    ));
    await tester.pumpAndSettle();

    expect(requested.path,
        '/api/v1/recommendations/professional-research/athena-synthesis/latest');
    expect(find.byKey(const Key('athena-synthesis-content')), findsOneWidget);
    expect(find.text('Resumen canónico'), findsOneWidget);
    expect(find.text('News verificada'), findsOneWidget);
    expect(find.text('Investors verificado'), findsOneWidget);

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

    await tester.pumpWidget(MaterialApp(
      home: DashboardPage(recommendationDependencies: dependencies),
    ));
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

    await tester.pumpWidget(MaterialApp(
      home: DashboardPage(recommendationDependencies: dependencies),
    ));
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
