import 'dart:async';
import 'dart:convert';

import 'package:app/features/news/models/verified_news_feed.dart';
import 'package:app/features/news/presentation/news_synthesis_controller.dart';
import 'package:app/features/news/presentation/pages/news_page.dart';
import 'package:app/features/news/presentation/widgets/news_feed_panel.dart';
import 'package:app/features/news/services/athena_backend_news_synthesis_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {

  testWidgets(
      'News rebind invalidates a pending request already owned by the new controller',
      (tester) async {
    final previousService = AthenaBackendNewsSynthesisService(
      baseUrl: 'https://athena.example',
      client: MockClient((_) async =>
          http.Response('{"detail":"unavailable"}', 503)),
    );
    final previousController = NewsSynthesisController(service: previousService);
    final pendingPriorMount = Completer<http.Response>();
    var reboundCalls = 0;
    final stale = _synthesisPayload();
    final staleSynthesis =
        (stale['data'] as Map<String, dynamic>)['synthesis']
            as Map<String, dynamic>;
    ((staleSynthesis['items'] as List).first
        as Map<String, dynamic>)['summary'] = 'Síntesis anterior en vuelo';
    final reboundService = AthenaBackendNewsSynthesisService(
      baseUrl: 'https://athena.example',
      client: MockClient((_) {
        reboundCalls++;
        if (reboundCalls == 1) return pendingPriorMount.future;
        return Future.value(http.Response(
          jsonEncode(_synthesisPayload()), 200,
          headers: {'content-type': 'application/json'},
        ));
      }),
    );
    final reboundController = NewsSynthesisController(service: reboundService);

    Widget page(NewsSynthesisController controller) => MaterialApp(
      home: NewsPage(
        synthesisController: controller,
        newsFeed: const SizedBox.shrink(),
      ),
    );

    await tester.pumpWidget(page(previousController));
    await tester.pumpAndSettle();
    unawaited(reboundController.load());
    await tester.pump();
    expect(reboundCalls, 1);

    await tester.pumpWidget(page(reboundController));
    await tester.pumpAndSettle();
    expect(reboundCalls, 2);
    expect(find.text('Síntesis renovada y verificable'), findsOneWidget);
    expect(find.text('Síntesis anterior en vuelo'), findsNothing);

    pendingPriorMount.complete(http.Response(
      jsonEncode(stale), 200,
      headers: {'content-type': 'application/json'},
    ));
    await tester.pump();
    expect(find.text('Síntesis renovada y verificable'), findsOneWidget);
    expect(find.text('Síntesis anterior en vuelo'), findsNothing);
    expect(tester.takeException(), isNull);

    await tester.pumpWidget(const SizedBox.shrink());
    previousController.dispose();
    previousService.dispose();
    reboundController.dispose();
    reboundService.dispose();
  });

  testWidgets('standalone News renders all verified articles in a scrollable page',
      (tester) async {
    final service = AthenaBackendNewsSynthesisService(
      baseUrl: 'https://athena.example',
      client: MockClient((_) async => http.Response('{"detail":"missing"}', 404)),
    );
    final controller = NewsSynthesisController(service: service);
    var requestedLimit = 0;

    await tester.pumpWidget(MaterialApp(
      home: NewsPage(
        synthesisController: controller,
        feedLoader: (limit) async {
          requestedLimit = limit;
          return _feed(20);
        },
      ),
    ));
    await tester.pumpAndSettle();

    expect(requestedLimit, 20);
    expect(find.text('Noticia verificada 1'), findsOneWidget);
    expect(find.textContaining('20 artículos · google_news_rss'), findsOneWidget);
    expect(tester.takeException(), isNull,
        reason: 'News page must not nest Expanded inside an unbounded scroll view');

    await tester.pumpWidget(const SizedBox.shrink());
    controller.dispose();
    service.dispose();
  });

  testWidgets('Dashboard keeps the height-constrained, independently scrollable feed',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: Center(
          child: SizedBox(
            width: 360,
            height: 320,
            child: NewsFeedPanel(
              limit: 8,
              loadFeed: (_) async => _feed(8),
            ),
          ),
        ),
      ),
    ));
    await tester.pumpAndSettle();

    expect(find.text('Noticia verificada 1'), findsOneWidget);
    expect(find.byType(ListView), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('News refresh recovers canonical synthesis independently of the feed',
      (tester) async {
    var synthesisCalls = 0;
    var feedCalls = 0;
    final service = AthenaBackendNewsSynthesisService(
      baseUrl: 'https://athena.example',
      client: MockClient((request) async {
        synthesisCalls++;
        expect(request.url.path,
            '/api/v1/recommendations/professional-research/news-synthesis/latest');
        if (synthesisCalls == 1) {
          return http.Response('{"detail":"temporarily unavailable"}', 503);
        }
        return http.Response(jsonEncode(_synthesisPayload()), 200,
            headers: {'content-type': 'application/json'});
      }),
    );
    final controller = NewsSynthesisController(service: service);
    await tester.pumpWidget(MaterialApp(
      home: NewsPage(
        synthesisController: controller,
        feedLoader: (_) async {
          feedCalls++;
          return _feed(1);
        },
      ),
    ));
    await tester.pumpAndSettle();

    expect(synthesisCalls, 1);
    expect(feedCalls, 1);
    expect(find.text('La síntesis verificada de noticias no está disponible.'),
        findsOneWidget);
    expect(find.text('Noticia verificada 1'), findsOneWidget);

    await tester.tap(find.byKey(const Key('news-page-refresh-synthesis')));
    await tester.pumpAndSettle();
    expect(synthesisCalls, 2);
    expect(feedCalls, 1);
    expect(find.text('Síntesis renovada y verificable'), findsOneWidget);
    expect(find.text('Noticia verificada 1'), findsOneWidget);
    expect(tester.takeException(), isNull);

    await tester.pumpWidget(const SizedBox.shrink());
    controller.dispose();
    service.dispose();
  });


  testWidgets('News refreshes feed and synthesis together without losing selective synthesis refresh',
      (tester) async {
    var synthesisCalls = 0;
    var feedCalls = 0;
    final service = AthenaBackendNewsSynthesisService(
      baseUrl: 'https://athena.example',
      client: MockClient((_) async {
        synthesisCalls++;
        final payload = _synthesisPayload();
        final synthesis = (payload['data'] as Map<String, dynamic>)['synthesis']
            as Map<String, dynamic>;
        (synthesis['items'] as List).first['summary'] =
            'Análisis ATHENA ciclo $synthesisCalls';
        return http.Response(jsonEncode(payload), 200,
            headers: {'content-type': 'application/json'});
      }),
    );
    final controller = NewsSynthesisController(service: service);
    await tester.pumpWidget(MaterialApp(
      home: NewsPage(
        synthesisController: controller,
        feedLoader: (_) async {
          feedCalls++;
          return _feed(1, prefix: 'Feed ciclo $feedCalls');
        },
      ),
    ));
    await tester.pumpAndSettle();

    expect(synthesisCalls, 1);
    expect(feedCalls, 1);
    expect(find.text('Feed ciclo 1 1'), findsOneWidget);
    expect(find.text('Análisis ATHENA ciclo 1'), findsOneWidget);

    await tester.tap(find.byKey(const Key('news-page-refresh-all')));
    await tester.pumpAndSettle();
    expect(synthesisCalls, 2);
    expect(feedCalls, 2);
    expect(find.text('Feed ciclo 1 1'), findsNothing);
    expect(find.text('Feed ciclo 2 1'), findsOneWidget);
    expect(find.text('Análisis ATHENA ciclo 1'), findsNothing);
    expect(find.text('Análisis ATHENA ciclo 2'), findsOneWidget);

    await tester.tap(find.byKey(const Key('news-page-refresh-synthesis')));
    await tester.pumpAndSettle();
    expect(synthesisCalls, 3);
    expect(feedCalls, 2, reason: 'Selective synthesis refresh must not reload the feed');
    expect(find.text('Análisis ATHENA ciclo 3'), findsOneWidget);
    expect(find.text('Feed ciclo 2 1'), findsOneWidget);
    expect(tester.takeException(), isNull);

    await tester.pumpWidget(const SizedBox.shrink());
    controller.dispose();
    service.dispose();
  });

  testWidgets('News combined refresh fails closed and rejects a late former feed',
      (tester) async {
    final oldFeed = Completer<VerifiedNewsFeed>();
    var feedCalls = 0;
    final service = AthenaBackendNewsSynthesisService(
      baseUrl: 'https://athena.example',
      client: MockClient((_) async =>
          http.Response('{"detail":"unavailable"}', 503)),
    );
    final controller = NewsSynthesisController(service: service);
    await tester.pumpWidget(MaterialApp(
      home: NewsPage(
        synthesisController: controller,
        feedLoader: (_) {
          feedCalls++;
          if (feedCalls == 1) return oldFeed.future;
          return Future<VerifiedNewsFeed>.error(StateError('provider unavailable'));
        },
      ),
    ));
    await tester.pump();

    await tester.tap(find.byKey(const Key('news-page-refresh-all')));
    await tester.pumpAndSettle();
    expect(feedCalls, 2);
    expect(find.text('Noticias no disponibles'), findsOneWidget);
    expect(find.text('La síntesis verificada de noticias no está disponible.'),
        findsOneWidget);

    oldFeed.complete(_feed(1, prefix: 'Resultado antiguo'));
    await tester.pump();
    expect(find.text('Resultado antiguo 1'), findsNothing);
    expect(find.text('Noticias no disponibles'), findsOneWidget);
    expect(tester.takeException(), isNull);

    await tester.pumpWidget(const SizedBox.shrink());
    controller.dispose();
    service.dispose();
  });

  testWidgets('replacing News feed loader discards a pending former source',
      (tester) async {
    final oldRequest = Completer<VerifiedNewsFeed>();
    Future<VerifiedNewsFeed> oldLoader(int _) => oldRequest.future;
    Future<VerifiedNewsFeed> newLoader(int _) async => _feed(1, prefix: 'Nueva');

    Widget host(Future<VerifiedNewsFeed> Function(int) loader) => MaterialApp(
      home: Scaffold(
        body: SizedBox(
          width: 360,
          height: 300,
          child: NewsFeedPanel(loadFeed: loader),
        ),
      ),
    );

    await tester.pumpWidget(host(oldLoader));
    await tester.pump();
    await tester.pumpWidget(host(newLoader));
    await tester.pumpAndSettle();
    expect(find.text('Nueva 1'), findsOneWidget);

    oldRequest.complete(_feed(1, prefix: 'Obsoleta'));
    await tester.pump();
    expect(find.text('Obsoleta 1'), findsNothing);
    expect(find.text('Nueva 1'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets('verified News exposes accessible HTTPS sources and copies the original link',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: SizedBox(
          width: 400,
          height: 340,
          child: NewsFeedPanel(
            limit: 1,
            loadFeed: (_) async => _feed(1),
          ),
        ),
      ),
    ));
    await tester.pumpAndSettle();

    const url = 'https://example.com/article/1';
    String? copied;
    final messenger = TestDefaultBinaryMessengerBinding
        .instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') {
        copied = (call.arguments as Map)['text'] as String;
      }
      return null;
    });
    addTearDown(() => messenger.setMockMethodCallHandler(SystemChannels.platform, null));
    expect(find.text(url), findsOneWidget);
    final sourceSemantics = tester.widget<Semantics>(
      find.ancestor(
        of: find.text(url),
        matching: find.byType(Semantics),
      ).first,
    );
    expect(sourceSemantics.properties.label, 'Enlace HTTPS de la noticia: $url');
    expect(
      find.byTooltip('Copiar enlace de Noticia verificada 1'),
      findsOneWidget,
    );
    await tester.tap(find.byTooltip('Copiar enlace de Noticia verificada 1'));
    await tester.pump();
    expect(copied, url);
    expect(find.text('Enlace de noticia copiado'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('News feed failure hides sources and retry restores verified provenance',
      (tester) async {
    var calls = 0;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: SizedBox(
          width: 400,
          height: 340,
          child: NewsFeedPanel(
            limit: 1,
            loadFeed: (_) {
              calls++;
              if (calls == 1) {
                return Future<VerifiedNewsFeed>.error(StateError('offline'));
              }
              return Future.value(_feed(1));
            },
          ),
        ),
      ),
    ));
    await tester.pumpAndSettle();

    expect(find.text('Noticias no disponibles'), findsOneWidget);
    expect(
      find.bySemanticsLabel('Noticias verificadas no disponibles.'),
      findsOneWidget,
    );
    expect(find.text('https://example.com/article/1'), findsNothing);
    expect(find.byIcon(Icons.copy_outlined), findsNothing);

    await tester.tap(find.text('Reintentar'));
    await tester.pumpAndSettle();
    expect(calls, 2);
    expect(find.text('Noticias no disponibles'), findsNothing);
    expect(find.text('https://example.com/article/1'), findsOneWidget);
    expect(find.byIcon(Icons.copy_outlined), findsOneWidget);
    expect(tester.takeException(), isNull);
  });


  testWidgets(
      'standalone News keeps verified synthesis when feed loader throws synchronously and retry recovers',
      (tester) async {
    var attempts = 0;
    final service = AthenaBackendNewsSynthesisService(
      baseUrl: 'https://athena.example',
      client: MockClient((_) async => http.Response(
        jsonEncode(_synthesisPayload()),
        200,
        headers: {'content-type': 'application/json'},
      )),
    );
    final controller = NewsSynthesisController(service: service);
    addTearDown(() {
      controller.dispose();
      service.dispose();
    });

    await tester.pumpWidget(MaterialApp(
      home: NewsPage(
        synthesisController: controller,
        feedLoader: (_) {
          attempts++;
          if (attempts == 1) {
            throw StateError('synchronous feed failure');
          }
          return Future.value(_feed(1, prefix: 'Recuperada'));
        },
      ),
    ));
    await tester.pumpAndSettle();

    expect(attempts, 1);
    expect(find.text('Noticias no disponibles'), findsOneWidget);
    expect(find.text('Síntesis renovada y verificable'), findsOneWidget);
    expect(find.text('Recuperada 1'), findsNothing);

    await tester.tap(find.text('Reintentar'));
    await tester.pumpAndSettle();
    expect(attempts, 2);
    expect(find.text('Noticias no disponibles'), findsNothing);
    expect(find.text('Recuperada 1'), findsOneWidget);
    expect(find.text('Síntesis renovada y verificable'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'replacing a pending feed with a synchronously failing source hides old articles and permits recovery',
      (tester) async {
    final pendingOldFeed = Completer<VerifiedNewsFeed>();
    Future<VerifiedNewsFeed> oldLoader(int _) => pendingOldFeed.future;
    Future<VerifiedNewsFeed> brokenLoader(int _) {
      throw StateError('replacement source failed synchronously');
    }
    Future<VerifiedNewsFeed> recoveredLoader(int _) async =>
        _feed(1, prefix: 'Nueva evidencia');

    Widget host(Future<VerifiedNewsFeed> Function(int) loader) => MaterialApp(
      home: Scaffold(
        body: SizedBox(
          width: 400,
          height: 340,
          child: NewsFeedPanel(limit: 1, loadFeed: loader),
        ),
      ),
    );

    await tester.pumpWidget(host(oldLoader));
    await tester.pump();
    await tester.pumpWidget(host(brokenLoader));
    await tester.pumpAndSettle();
    expect(find.text('Noticias no disponibles'), findsOneWidget);
    expect(find.text('Noticia antigua 1'), findsNothing);

    pendingOldFeed.complete(_feed(1, prefix: 'Noticia antigua'));
    await tester.pump();
    expect(find.text('Noticia antigua 1'), findsNothing);
    expect(find.text('Noticias no disponibles'), findsOneWidget);

    await tester.pumpWidget(host(recoveredLoader));
    await tester.pumpAndSettle();
    expect(find.text('Noticias no disponibles'), findsNothing);
    expect(find.text('Nueva evidencia 1'), findsOneWidget);
    expect(find.text('Noticia antigua 1'), findsNothing);
    expect(tester.takeException(), isNull);
  });

}

VerifiedNewsFeed _feed(int count, {String prefix = 'Noticia verificada'}) {
  return VerifiedNewsFeed.fromMap({
    'status': 'news_feed_ready',
    'query': 'stock market earnings economy',
    'count': count,
    'sourceProvider': 'google_news_rss',
    'retrievedAt': '2026-10-25T10:00:00Z',
    'items': List.generate(count, (index) => {
      'title': '$prefix ${index + 1}',
      'publisher': 'Fuente verificable',
      'publisherUrl': 'https://example.com',
      'articleUrl': 'https://example.com/article/${index + 1}',
      'publishedAt': '2026-10-25T09:30:00Z',
      'retrievedAt': '2026-10-25T10:00:00Z',
      'sourceProvider': 'google_news_rss',
    }),
    'policy': {
      'athenaRecommendationInfluence': false,
      'automaticScoring': false,
      'automaticTrading': false,
    },
    'advisoryStatus': 'no_advice',
    'productionEligible': false,
  });
}

Map<String, dynamic> _synthesisPayload() => {
  'data': {
    'cycleBindingVerified': true,
    'presentationOnly': true,
    'cycleHash': 'a' * 64,
    'radarHash': 'b' * 64,
    'synthesis': {
      'status': 'validated_external_model_output',
      'asOf': '2026-10-25T06:00:00Z',
      'minimumImportance': 'low',
      'assessedCount': 1,
      'includedCount': 1,
      'excludedCount': 0,
      'items': [
        {
          'evidenceId': 'news-acceptance-1',
          'symbol': 'AAPL',
          'sourceRef': 'https://example.com/article/1',
          'evidenceProvider': 'google_news_rss',
          'publisher': 'Fuente verificable',
          'modelProvider': 'external_research_model',
          'modelName': 'news-synthesis',
          'modelVersion': '1.0',
          'inputFingerprint': 'c' * 64,
          'assessmentFingerprint': 'd' * 64,
          'summary': 'Síntesis renovada y verificable',
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
      'createdAt': '2026-10-25T06:01:00Z',
    },
    'recommendationInfluence': false,
    'automaticScoring': false,
    'automaticTrading': false,
  },
};
