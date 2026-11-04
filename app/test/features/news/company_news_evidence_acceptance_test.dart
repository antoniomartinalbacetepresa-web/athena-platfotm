import 'dart:convert';

import 'package:app/core/routing/app_routes.dart';
import 'package:app/features/news/presentation/news_synthesis_controller.dart';
import 'package:app/features/news/presentation/pages/news_page.dart';
import 'package:app/features/news/services/athena_backend_news_synthesis_service.dart';
import 'package:app/features/news/models/company_news_evidence.dart';
import 'package:app/features/news/presentation/widgets/company_news_evidence_panel.dart';
import 'package:app/features/news/services/athena_backend_company_news_evidence_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

Map<String, dynamic> payload() {
  final now = DateTime.now().toUtc().subtract(const Duration(minutes: 2));
  final published = now.subtract(const Duration(minutes: 10));
  return {
    'data': {
      'status': 'news_evidence_ready',
      'symbol': 'ACME',
      'companyName': 'Acme Corporation',
      'sourceProvider': 'google_news_rss',
      'retrievedAt': now.toIso8601String(),
      'asOf': null,
      'acceptedCount': 1,
      'rejectedCount': 2,
      'provenanceComplete': true,
      'productionTruthClaimed': false,
      'independentCorroborationClaimed': false,
      'issuerIdentityIndependentlyVerified': false,
      'headlineMentionRequired': true,
      'recommendationInfluence': false,
      'automaticScoring': false,
      'automaticTrading': false,
      'mode': 'research_evidence_only',
      'advisoryStatus': 'no_advice',
      'readOnly': true,
      'productionEligible': false,
      'licenseVerified': false,
      'modelExecutionVerified': false,
      'persisted': false,
      'evidence': [{
        'evidenceId': 'news:123456789012345678901234',
        'category': 'news',
        'urgency': 'routine',
        'summary': 'Acme announces results',
        'availableAt': now.toIso8601String(),
        'source': 'news',
        'sourceRef': 'https://news.google.com/rss/articles/acme',
        'provider': 'google_news_rss',
        'publisher': 'Example Publisher',
        'publishedAt': published.toIso8601String(),
      }],
    },
  };
}

CompanyNewsEvidence parse(Map<String, dynamic> data) =>
    CompanyNewsEvidence.fromMap(data,
      requestedSymbol: 'ACME', requestedCompanyName: 'Acme Corporation');

void main() {
  test('typed client calls company evidence endpoint with encoded issuer and symbol', () async {
    final service = AthenaBackendCompanyNewsEvidenceService(
      baseUrl: 'https://athena.example',
      client: MockClient((request) async {
        expect(request.url.path, '/api/v1/news/company-evidence');
        expect(request.url.queryParameters['symbol'], 'ACME');
        expect(request.url.queryParameters['companyName'], 'Acme Corporation');
        return http.Response(jsonEncode(payload()), 200);
      }),
    );
    addTearDown(service.dispose);
    final result = await service.getEvidence(
      symbol: 'acme', companyName: 'Acme Corporation');
    expect(result.items.single.summary, 'Acme announces results');
    expect(result.rejectedCount, 2);
  });

  test('rejects mismatched issuer and unsafe authority claims', () {
    final wrong = payload();
    (wrong['data'] as Map<String, dynamic>)['symbol'] = 'OTHER';
    expect(() => parse(wrong), throwsFormatException);
    final authority = payload();
    (authority['data'] as Map<String, dynamic>)['automaticTrading'] = true;
    expect(() => parse(authority), throwsFormatException);
    final fakeLicense = payload();
    (fakeLicense['data'] as Map<String, dynamic>)['licenseVerified'] = true;
    expect(() => parse(fakeLicense), throwsFormatException);
  });

  test('rejects future retrieval and tampered PIT provenance', () {
    final future = payload();
    (future['data'] as Map<String, dynamic>)['retrievedAt'] =
        DateTime.now().toUtc().add(const Duration(minutes: 2)).toIso8601String();
    expect(() => parse(future), throwsFormatException);
    final mismatched = payload();
    final item = ((mismatched['data'] as Map<String, dynamic>)['evidence'] as List)
        .first as Map<String, dynamic>;
    item['sourceRef'] = 'http://unsafe.example/article';
    expect(() => parse(mismatched), throwsFormatException);
  });

  testWidgets('company News opens a symbol-only ATHENA dossier with explicit unbound identity',
      (tester) async {
    final synthesisService = AthenaBackendNewsSynthesisService(
      baseUrl: 'https://athena.example',
      client: MockClient((_) async => http.Response('{"detail":"missing"}', 404)),
    );
    final controller = NewsSynthesisController(service: synthesisService);
    addTearDown(controller.dispose);
    addTearDown(synthesisService.dispose);
    String? openedRoute;
    await tester.pumpWidget(MaterialApp(
      home: NewsPage(
        symbol: 'ACME',
        companyName: 'Acme Corporation',
        synthesisController: controller,
        newsFeed: const SizedBox.shrink(),
        companyEvidenceLoader: (_, _) async => parse(payload()),
      ),
      onGenerateRoute: (settings) {
        openedRoute = settings.name;
        return MaterialPageRoute<void>(
          settings: settings,
          builder: (_) => const Scaffold(body: Text('Destino de investigación')),
        );
      },
    ));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('news-research-navigation-boundary')), findsOneWidget);
    await tester.ensureVisible(find.byKey(const Key('news-open-company-research')));
    await tester.tap(find.byKey(const Key('news-open-company-research')));
    await tester.pumpAndSettle();
    expect(openedRoute, '${AppRoutes.stockResearch}?symbol=ACME');
    expect(find.text('Destino de investigación'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('company evidence displays source, date, uncertainty and no-advice boundary',
      (tester) async {
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: SingleChildScrollView(
      child: CompanyNewsEvidencePanel(
        symbol: 'ACME', companyName: 'Acme Corporation',
        loadEvidence: (_, _) async => parse(payload()),
      ),
    ))));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('company-news-evidence-boundary')), findsOneWidget);
    expect(find.text('Acme announces results'), findsOneWidget);
    expect(find.text('https://news.google.com/rss/articles/acme'), findsOneWidget);
    expect(find.textContaining('2 descartadas'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('contradictory company evidence never retains a previous headline',
      (tester) async {
    var calls = 0;
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: SingleChildScrollView(
      child: CompanyNewsEvidencePanel(
        symbol: 'ACME', companyName: 'Acme Corporation',
        loadEvidence: (_, _) {
          calls++;
          if (calls == 1) return Future.value(parse(payload()));
          final wrong = parse(payload());
          return Future.value(CompanyNewsEvidence(
            symbol: 'OTHER', companyName: wrong.companyName,
            provider: wrong.provider, retrievedAt: wrong.retrievedAt,
            rejectedCount: wrong.rejectedCount, items: wrong.items,
          ));
        },
      ),
    ))));
    await tester.pumpAndSettle();
    expect(find.text('Acme announces results'), findsOneWidget);
    await tester.tap(find.text('Actualizar evidencia'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('company-news-evidence-error')), findsOneWidget);
    expect(find.text('Acme announces results'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
