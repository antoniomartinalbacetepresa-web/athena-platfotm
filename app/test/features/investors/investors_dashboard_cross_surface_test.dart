import 'dart:convert';

import 'package:app/core/routing/app_routes.dart';
import 'package:app/features/dashboard/presentation/pages/dashboard_page.dart';
import 'package:app/features/investors/presentation/pages/investors_page.dart';
import 'package:app/features/recommendations/controllers/athena_synthesis_controller.dart';
import 'package:app/features/recommendations/controllers/recommendation_learning_controller.dart';
import 'package:app/features/recommendations/data/datasources/athena_backend_professional_dossier_data_source.dart';
import 'package:app/features/recommendations/data/datasources/athena_backend_recommendation_learning_data_source.dart';
import 'package:app/features/recommendations/data/datasources/athena_backend_recommendation_production_data_source.dart';
import 'package:app/features/recommendations/data/datasources/athena_backend_recommendation_shadow_candidate_data_source.dart';
import 'package:app/features/recommendations/data/datasources/athena_backend_synthesis_data_source.dart';
import 'package:app/features/recommendations/di/recommendation_dependencies.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  testWidgets(
      'Dashboard to Investors route refreshes SEC/research only and fails closed',
      (tester) async {
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var synthesisRequests = 0;
    const baseUrl = 'https://athena.example';
    final synthesis = AthenaBackendSynthesisDataSource(
      baseUrl: baseUrl,
      client: MockClient((_) async {
        synthesisRequests++;
        return http.Response(
          jsonEncode({'detail': 'canonical evidence unavailable'}),
          503,
        );
      }),
    );
    final ancillary = MockClient((_) async => http.Response('{}', 404));
    final learning = AthenaBackendRecommendationLearningDataSource(
      baseUrl: baseUrl, client: ancillary,
    );
    final dependencies = RecommendationDependencies(
      learningDataSource: learning,
      shadowCandidateDataSource:
          AthenaBackendRecommendationShadowCandidateDataSource(
            baseUrl: baseUrl, client: ancillary,
          ),
      productionDataSource: AthenaBackendRecommendationProductionDataSource(
        baseUrl: baseUrl, client: ancillary,
      ),
      professionalDossierDataSource:
          AthenaBackendProfessionalDossierDataSource(
            baseUrl: baseUrl, client: ancillary,
          ),
      synthesisDataSource: synthesis,
      learningController: RecommendationLearningController(provider: learning),
      synthesisController: AthenaSynthesisController(dataSource: synthesis),
    );
    addTearDown(dependencies.dispose);

    await tester.pumpWidget(MaterialApp(
      home: DashboardPage(
        recommendationDependencies: dependencies,
        operationalPanelsBuilder:
            (owner, market, news, investors, research, readiness) => Column(
          children: [
            SizedBox(key: Key('owner-$owner'), height: 1),
            SizedBox(key: Key('market-$market'), height: 1),
            SizedBox(key: Key('news-$news'), height: 1),
            SizedBox(key: Key('investors-$investors'), height: 1),
            SizedBox(key: Key('research-$research'), height: 1),
            SizedBox(key: Key('readiness-$readiness'), height: 1),
          ],
        ),
      ),
      onGenerateRoute: (settings) {
        if (settings.name != AppRoutes.investors) return null;
        return MaterialPageRoute<void>(
          settings: settings,
          builder: (_) => const InvestorsPage(configuredCiks: []),
        );
      },
    ));
    await tester.pumpAndSettle();
    expect(synthesisRequests, 1);
    expect(find.byKey(const Key('athena-synthesis-error')), findsOneWidget);
    expect(find.byKey(const Key('investors-0')), findsOneWidget);

    await tester.tap(find.byTooltip('Inversores'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('investors-page-heading')), findsOneWidget);
    expect(find.text('Sin inversores configurados'), findsOneWidget);
    expect(
      ModalRoute.of(tester.element(find.byKey(const Key('investors-page-heading'))))
          ?.settings.name,
      AppRoutes.investors,
    );

    Navigator.of(tester.element(find.byKey(const Key('investors-page-heading'))))
        .pop();
    await tester.pumpAndSettle();

    expect(synthesisRequests, 2);
    expect(find.byKey(const Key('athena-synthesis-error')), findsOneWidget);
    expect(find.byKey(const Key('investors-1')), findsOneWidget);
    expect(find.byKey(const Key('research-1')), findsOneWidget);
    expect(find.byKey(const Key('readiness-1')), findsOneWidget);
    expect(find.byKey(const Key('market-0')), findsOneWidget);
    expect(find.byKey(const Key('news-0')), findsOneWidget);
    expect(find.byKey(const Key('owner-0')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
