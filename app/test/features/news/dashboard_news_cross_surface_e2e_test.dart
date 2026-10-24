import 'dart:convert';

import 'package:app/core/routing/app_routes.dart';
import 'package:app/features/dashboard/presentation/widgets/dashboard_header.dart';
import 'package:app/features/news/presentation/news_synthesis_controller.dart';
import 'package:app/features/news/presentation/pages/news_page.dart';
import 'package:app/features/news/services/athena_backend_news_synthesis_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  testWidgets(
      'Dashboard to News preserves canonical PIT provenance and no-authority boundary',
      (tester) async {
    final requested = <Uri>[];
    final service = AthenaBackendNewsSynthesisService(
      baseUrl: 'https://athena.example',
      client: MockClient((request) async {
        requested.add(request.url);
        return http.Response(
          jsonEncode(_payload()),
          200,
          headers: {'content-type': 'application/json'},
        );
      }),
    );
    final controller = NewsSynthesisController(service: service);

    await tester.pumpWidget(
      MaterialApp(
        home: const Scaffold(body: SizedBox(width: 900, child: DashboardHeader())),
        onGenerateRoute: (settings) {
          if (settings.name == AppRoutes.news) {
            return MaterialPageRoute<void>(
              settings: settings,
              builder: (_) => NewsPage(
                synthesisController: controller,
                newsFeed: const SizedBox.shrink(),
              ),
            );
          }
          return null;
        },
      ),
    );

    await tester.tap(find.byTooltip('Noticias'));
    await tester.pumpAndSettle();

    expect(ModalRoute.of(tester.element(find.text('NOTICIAS')))?.settings.name,
        AppRoutes.news);
    expect(requested, hasLength(1));
    expect(
      requested.single.path,
      '/api/v1/recommendations/professional-research/news-synthesis/latest',
    );
    final pageHeading = tester.widget<Semantics>(
      find.ancestor(
        of: find.byKey(const Key('news-page-heading')),
        matching: find.byType(Semantics),
      ).first,
    );
    expect(pageHeading.properties.header, isTrue);
    expect(find.text('ANÁLISIS ATHENA DE NOTICIAS'), findsOneWidget);
    expect(find.textContaining('Resultados auditables'), findsOneWidget);
    expect(find.textContaining('Example Publisher'), findsOneWidget);
    expect(find.text('https://example.com/news/aapl'), findsOneWidget);

    final semantics = tester.getSemantics(
      find.bySemanticsLabel(
        'Síntesis informativa basada en evidencia point-in-time. No es una recomendación de inversión y no ejecuta operaciones.',
      ),
    );
    expect(semantics.label, contains('No es una recomendación'));
    expect(semantics.label, contains('no ejecuta operaciones'));

    final itemSemantics = tester.getSemantics(
      find.bySemanticsLabel(
        'Estimación incierta para AAPL: impacto positive, magnitud 70 por ciento y confianza 80 por ciento. Es información diagnóstica; no autoriza recomendaciones ni operaciones.',
      ),
    );
    expect(itemSemantics.label, contains('magnitud 70 por ciento'));
    expect(itemSemantics.label, contains('confianza 80 por ciento'));
    expect(itemSemantics.label, contains('no autoriza recomendaciones ni operaciones'));

    await tester.pumpWidget(const SizedBox.shrink());
    controller.dispose();
    service.dispose();
  });

  testWidgets(
      'Dashboard News re-entry fails closed after 503 and recovers only on verified retry',
      (tester) async {
    var calls = 0;
    final recoveredPayload = _payload();
    final recoveredSynthesis =
        (recoveredPayload['data'] as Map<String, dynamic>)['synthesis']
            as Map<String, dynamic>;
    ((recoveredSynthesis['items'] as List).single
        as Map<String, dynamic>)['summary'] =
        'Nueva evidencia validada tras reintentar.';

    final service = AthenaBackendNewsSynthesisService(
      baseUrl: 'https://athena.example',
      client: MockClient((request) async {
        calls++;
        expect(
          request.url.path,
          '/api/v1/recommendations/professional-research/news-synthesis/latest',
        );
        if (calls == 2) {
          return http.Response('{"detail":"unavailable"}', 503);
        }
        return http.Response(
          jsonEncode(calls == 1 ? _payload() : recoveredPayload),
          200,
          headers: {'content-type': 'application/json'},
        );
      }),
    );
    final controller = NewsSynthesisController(service: service);
    await tester.pumpWidget(
      MaterialApp(
        home: const Scaffold(body: SizedBox(width: 900, child: DashboardHeader())),
        onGenerateRoute: (settings) {
          if (settings.name == AppRoutes.news) {
            return MaterialPageRoute<void>(
              settings: settings,
              builder: (_) => NewsPage(
                synthesisController: controller,
                newsFeed: const SizedBox.shrink(),
              ),
            );
          }
          return null;
        },
      ),
    );

    await tester.tap(find.byTooltip('Noticias'));
    await tester.pumpAndSettle();
    expect(calls, 1);
    expect(find.textContaining('Resultados auditables'), findsOneWidget);

    tester.state<NavigatorState>(find.byType(Navigator)).pop();
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Noticias'));
    await tester.pumpAndSettle();

    expect(calls, 2);
    expect(find.textContaining('Resultados auditables'), findsNothing);
    expect(find.text('Reintentar'), findsOneWidget);
    expect(find.text('ANÁLISIS ATHENA DE NOTICIAS'), findsNothing);

    await tester.tap(find.text('Reintentar'));
    await tester.pumpAndSettle();
    expect(calls, 3);
    expect(find.text('Nueva evidencia validada tras reintentar.'), findsOneWidget);
    expect(find.textContaining('Resultados auditables'), findsNothing);

    await tester.pumpWidget(const SizedBox.shrink());
    controller.dispose();
    service.dispose();
  });

}

Map<String, dynamic> _payload() => {
      'data': {
        'cycleBindingVerified': true,
        'presentationOnly': true,
        'cycleHash': 'a' * 64,
        'radarHash': 'b' * 64,
        'synthesis': {
          'status': 'validated_external_model_output',
          'asOf': '2026-09-29T06:00:00Z',
          'minimumImportance': 'low',
          'assessedCount': 1,
          'includedCount': 1,
          'excludedCount': 0,
          'items': [
            {
              'evidenceId': 'news-cross-surface-1',
              'symbol': 'AAPL',
              'sourceRef': 'https://example.com/news/aapl',
              'evidenceProvider': 'google_news_rss',
              'publisher': 'Example Publisher',
              'modelProvider': 'external_research_model',
              'modelName': 'news-synthesis',
              'modelVersion': '1.0',
              'inputFingerprint': 'c' * 64,
              'assessmentFingerprint': 'd' * 64,
              'summary': 'Resultados auditables sujetos a verificación independiente.',
              'importance': 'high',
              'impactDirection': 'positive',
              'impactMagnitude': 0.7,
              'confidence': 0.8,
            },
          ],
          'modelExecutionVerified': false,
          'productionTruthClaimed': false,
          'independentCorroborationClaimed': false,
          'recommendationInfluence': false,
          'automaticScoring': false,
          'automaticTrading': false,
        },
        'persistence': {
          'appendOnly': true,
          'packageIntegrityVerified': true,
          'synthesisHash': 'e' * 64,
          'createdAt': '2026-09-29T06:01:00Z',
        },
        'recommendationInfluence': false,
        'automaticScoring': false,
        'automaticTrading': false,
      },
    };
