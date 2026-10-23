import 'dart:async';
import 'dart:convert';

import 'package:app/features/news/models/verified_news_synthesis.dart';
import 'package:app/features/news/presentation/news_synthesis_controller.dart';
import 'package:app/features/news/presentation/pages/news_page.dart';
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

  test('PIT timestamp requires an explicit UTC offset', () {
    final missingTimezone = payload();
    final synthesis = (missingTimezone['data'] as Map<String, dynamic>)['synthesis']
        as Map<String, dynamic>;
    synthesis['asOf'] = '2026-09-17T17:00:00';
    expect(
      () => VerifiedNewsSynthesis.fromMap(missingTimezone),
      throwsFormatException,
    );

    final explicitOffset = payload();
    final validSynthesis = (explicitOffset['data'] as Map<String, dynamic>)
        ['synthesis'] as Map<String, dynamic>;
    validSynthesis['asOf'] = '2026-09-17T19:00:00+02:00';
    expect(
      VerifiedNewsSynthesis.fromMap(explicitOffset).items,
      hasLength(1),
    );
  });

  test('unknown importance filter fails closed', () {
    final unsafe = payload();
    final synthesis =
        (unsafe['data'] as Map<String, dynamic>)['synthesis'] as Map<String, dynamic>;
    synthesis['minimumImportance'] = 'unfiltered';
    expect(() => VerifiedNewsSynthesis.fromMap(unsafe), throwsFormatException);
  });

  test('HTTPS provenance cannot embed misleading URL credentials', () {
    final unsafe = payload();
    final synthesis =
        (unsafe['data'] as Map<String, dynamic>)['synthesis'] as Map<String, dynamic>;
    final item = (synthesis['items'] as List).single as Map<String, dynamic>;
    item['sourceRef'] = 'https://publisher.example@attacker.example/news';
    expect(() => VerifiedNewsSynthesis.fromMap(unsafe), throwsFormatException);
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

  testWidgets('canonical News timeout fails closed and retry restores verified evidence',
      (tester) async {
    var calls = 0;
    final service = AthenaBackendNewsSynthesisService(
      baseUrl: 'http://127.0.0.1:8000',
      requestTimeout: const Duration(milliseconds: 25),
      client: MockClient((_) {
        calls++;
        if (calls == 1) return Completer<http.Response>().future;
        return Future.value(http.Response(jsonEncode(payload()), 200));
      }),
    );
    final controller = NewsSynthesisController(service: service);
    await controller.load();
    expect(controller.error, isA<TimeoutException>());
    expect(controller.synthesis, isNull);
    expect(controller.loading, isFalse);

    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: NewsSynthesisPanel(controller: controller)),
    ));
    expect(find.text('Reintentar'), findsOneWidget);
    expect(find.textContaining('Resultados mejores'), findsNothing);

    await controller.retry();
    await tester.pump();
    expect(calls, 2);
    expect(controller.error, isNull);
    expect(find.textContaining('Resultados mejores'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    controller.dispose();
    service.dispose();
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

  testWidgets('News page loads the canonical synthesis through its injected boundary',
      (tester) async {
    var calls = 0;
    final service = AthenaBackendNewsSynthesisService(
      baseUrl: 'http://127.0.0.1:8000',
      client: MockClient((request) async {
        calls += 1;
        return http.Response(jsonEncode(payload()), 200);
      }),
    );
    final controller = NewsSynthesisController(service: service);

    await tester.pumpWidget(MaterialApp(
      home: NewsPage(
        synthesisController: controller,
        newsFeed: const SizedBox.shrink(),
      ),
    ));
    await tester.pump();
    await tester.pump();

    expect(calls, 1);
    expect(find.text('NOTICIAS'), findsOneWidget);
    expect(find.textContaining('Resultados mejores'), findsOneWidget);
    expect(find.textContaining('Example Publisher'), findsOneWidget);

    await tester.pumpWidget(const SizedBox.shrink());
    controller.dispose();
    service.dispose();
  });


  test('News clear invalidates a pending failure without replacing newer evidence',
      () async {
    final firstResponse = Completer<http.Response>();
    final secondResponse = Completer<http.Response>();
    var calls = 0;
    final service = AthenaBackendNewsSynthesisService(
      baseUrl: 'http://127.0.0.1:8000',
      client: MockClient((_) {
        calls++;
        return calls == 1 ? firstResponse.future : secondResponse.future;
      }),
    );
    final controller = NewsSynthesisController(service: service);
    var notifications = 0;
    controller.addListener(() => notifications++);

    final staleLoad = controller.load();
    expect(controller.loading, isTrue);
    controller.clear();
    expect(controller.loading, isFalse);
    expect(controller.synthesis, isNull);
    final currentLoad = controller.load();
    // http.Client.get dispatches through an asynchronous send boundary.
    // Let both requests reach the mock before checking their order.
    await Future<void>.delayed(Duration.zero);
    expect(calls, 2);

    secondResponse.complete(http.Response(jsonEncode(payload()), 200));
    await currentLoad;
    expect(controller.synthesis?.items.single.evidenceId, 'news-1');
    expect(controller.error, isNull);
    final notificationsAfterCurrent = notifications;

    firstResponse.complete(http.Response('{"detail":"old failure"}', 503));
    await staleLoad;
    expect(controller.synthesis?.items.single.evidenceId, 'news-1');
    expect(controller.error, isNull);
    expect(controller.loading, isFalse);
    expect(notifications, notificationsAfterCurrent);

    controller.dispose();
    service.dispose();
  });

  test('News disposal ignores a late response without notifying listeners',
      () async {
    final response = Completer<http.Response>();
    final service = AthenaBackendNewsSynthesisService(
      baseUrl: 'http://127.0.0.1:8000',
      client: MockClient((_) => response.future),
    );
    final controller = NewsSynthesisController(service: service);
    var notifications = 0;
    controller.addListener(() => notifications++);

    final pending = controller.load();
    final notificationsBeforeDispose = notifications;
    controller.dispose();
    response.complete(http.Response(jsonEncode(payload()), 200));
    await pending;

    expect(controller.synthesis, isNull);
    expect(notifications, notificationsBeforeDispose);
    service.dispose();
  });

  testWidgets('News page rebinds an injected controller without stale synthesis',
      (tester) async {
    final firstPayload = payload();
    final firstSynthesis =
        (firstPayload['data'] as Map<String, dynamic>)['synthesis']
            as Map<String, dynamic>;
    (firstSynthesis['items'] as List).single['summary'] =
        'Síntesis del controlador anterior.';
    final secondPayload = payload();
    final secondSynthesis =
        (secondPayload['data'] as Map<String, dynamic>)['synthesis']
            as Map<String, dynamic>;
    (secondSynthesis['items'] as List).single['summary'] =
        'Síntesis del nuevo controlador.';

    final firstService = AthenaBackendNewsSynthesisService(
      baseUrl: 'http://127.0.0.1:8000',
      client: MockClient((_) async =>
          http.Response(jsonEncode(firstPayload), 200)),
    );
    final secondService = AthenaBackendNewsSynthesisService(
      baseUrl: 'http://127.0.0.1:8000',
      client: MockClient((_) async =>
          http.Response(jsonEncode(secondPayload), 200)),
    );
    final firstController = NewsSynthesisController(service: firstService);
    final secondController = NewsSynthesisController(service: secondService);

    await tester.pumpWidget(MaterialApp(
      home: NewsPage(
        synthesisController: firstController,
        newsFeed: const SizedBox.shrink(),
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Síntesis del controlador anterior.'), findsOneWidget);

    await tester.pumpWidget(MaterialApp(
      home: NewsPage(
        synthesisController: secondController,
        newsFeed: const SizedBox.shrink(),
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Síntesis del controlador anterior.'), findsNothing);
    expect(find.text('Síntesis del nuevo controlador.'), findsOneWidget);

    await tester.pumpWidget(const SizedBox.shrink());
    firstController.dispose();
    secondController.dispose();
    firstService.dispose();
    secondService.dispose();
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
