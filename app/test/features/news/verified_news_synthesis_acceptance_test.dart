import 'dart:convert';

import 'package:app/features/news/models/verified_news_synthesis.dart';
import 'package:app/features/news/presentation/news_synthesis_controller.dart';
import 'package:app/features/news/presentation/widgets/news_synthesis_panel.dart';
import 'package:app/features/news/services/athena_backend_news_synthesis_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  Map<String, dynamic> payload() => {
        'data': {
          'cycleBindingVerified': true,
          'presentationOnly': true,
          'cycleHash': 'a' * 64,
          'radarHash': 'b' * 64,
          'synthesis': {
            'status': 'validated_external_model_output',
            'asOf': '2026-09-17T17:00:00Z',
            'minimumImportance': 'low',
            'assessedCount': 1,
            'includedCount': 1,
            'excludedCount': 0,
            'items': [
              {
                'evidenceId': 'news-1',
                'symbol': 'AAPL',
                'sourceRef': 'https://example.com/news/aapl',
                'evidenceProvider': 'google_news_rss',
                'publisher': 'Example Publisher',
                'modelProvider': 'external_research_model',
                'modelName': 'news-synthesis',
                'modelVersion': '1.0',
                'inputFingerprint': 'c' * 64,
                'assessmentFingerprint': 'd' * 64,
                'summary': 'Resultados mejores de lo esperado, sujetos a verificación.',
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
            'createdAt': '2026-09-17T17:01:00Z',
          },
          'recommendationInfluence': false,
          'automaticScoring': false,
          'automaticTrading': false,
        },
      };

  test('acceptance contract preserves summary impact confidence and provenance', () {
    final synthesis = VerifiedNewsSynthesis.fromMap(payload());
    final item = synthesis.items.single;
    expect(item.summary, contains('Resultados'));
    expect(item.importance, 'high');
    expect(item.impactDirection, 'positive');
    expect(item.impactMagnitude, 0.7);
    expect(item.confidence, 0.8);
    expect(item.publisher, 'Example Publisher');
    expect(item.sourceRef, startsWith('https://'));
  });

  test('acceptance contract fails closed on authority escalation and FMP', () {
    final unsafe = payload();
    (unsafe['data'] as Map<String, dynamic>)['automaticTrading'] = true;
    expect(() => VerifiedNewsSynthesis.fromMap(unsafe), throwsFormatException);

    final fmp = payload();
    final synthesis = (fmp['data'] as Map<String, dynamic>)['synthesis'] as Map<String, dynamic>;
    final item = (synthesis['items'] as List).single as Map<String, dynamic>;
    item['evidenceProvider'] = 'Financial Modeling Prep';
    expect(() => VerifiedNewsSynthesis.fromMap(fmp), throwsFormatException);
  });

  test('transport uses only canonical latest endpoint', () async {
    late Uri requested;
    final service = AthenaBackendNewsSynthesisService(
      baseUrl: 'http://127.0.0.1:8000',
      client: MockClient((request) async {
        requested = request.url;
        return http.Response(jsonEncode(payload()), 200);
      }),
    );
    final result = await service.getLatest();
    expect(requested.path,
        '/api/v1/recommendations/professional-research/news-synthesis/latest');
    expect(result.items.single.evidenceId, 'news-1');
  });

  testWidgets('vertical UI exposes synthesis and clears stale data on retry failure',
      (tester) async {
    var calls = 0;
    final service = AthenaBackendNewsSynthesisService(
      baseUrl: 'http://127.0.0.1:8000',
      client: MockClient((request) async {
        calls += 1;
        if (calls == 1) return http.Response(jsonEncode(payload()), 200);
        return http.Response('{"detail":"unavailable"}', 503);
      }),
    );
    final controller = NewsSynthesisController(service: service);
    await controller.load();

    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: NewsSynthesisPanel(controller: controller)),
    ));
    expect(find.textContaining('Resultados mejores'), findsOneWidget);
    expect(find.textContaining('Impacto estimado: positive'), findsOneWidget);
    expect(find.textContaining('Example Publisher'), findsOneWidget);

    await controller.retry();
    await tester.pump();
    expect(controller.synthesis, isNull);
    expect(controller.error, isNotNull);
    expect(find.textContaining('Resultados mejores'), findsNothing);
    expect(find.text('Reintentar'), findsOneWidget);
    controller.dispose();
    service.dispose();
  });

  testWidgets('404 produces verified empty/error state without fabricated synthesis',
      (tester) async {
    final service = AthenaBackendNewsSynthesisService(
      baseUrl: 'http://127.0.0.1:8000',
      client: MockClient((request) async => http.Response('{"detail":"none"}', 404)),
    );
    final controller = NewsSynthesisController(service: service);
    await controller.load();
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: NewsSynthesisPanel(controller: controller)),
    ));
    expect(controller.synthesis, isNull);
    expect(find.text('Reintentar'), findsOneWidget);
    expect(find.textContaining('ANÁLISIS ATHENA'), findsNothing);
    controller.dispose();
    service.dispose();
  });
}
