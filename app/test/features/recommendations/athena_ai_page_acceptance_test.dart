import 'dart:async';
import 'dart:convert';

import 'package:app/features/recommendations/controllers/athena_synthesis_controller.dart';
import 'package:app/features/recommendations/data/datasources/athena_backend_synthesis_data_source.dart';
import 'package:app/features/recommendations/presentation/pages/athena_ai_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  testWidgets('ATHENA AI rejects failed evidence and recovers with provenance',
      (tester) async {
    var calls = 0;
    final source = AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((request) async {
        calls++;
        expect(request.url.path,
            '/api/v1/recommendations/professional-research/athena-synthesis/latest');
        if (calls == 1) return http.Response('{"detail":"private token"}', 503);
        return http.Response(jsonEncode(_payload('Nueva síntesis verificada')), 200);
      }),
    );
    final controller = AthenaSynthesisController(dataSource: source);
    addTearDown(controller.dispose);
    addTearDown(source.dispose);
    await tester.pumpWidget(MaterialApp(home: AthenaAiPage(controller: controller)));
    await tester.pumpAndSettle();

    expect(calls, 1);
    expect(find.byKey(const Key('athena-ai-page-heading')), findsOneWidget);
    expect(find.byKey(const Key('athena-synthesis-error')), findsOneWidget);
    expect(find.textContaining('private token'), findsNothing);
    expect(
      find.bySemanticsLabel(
        'ATHENA AI muestra solo síntesis canónicas verificadas. '
        'No autoriza recomendaciones, ponderaciones ni operaciones.',
      ),
      findsOneWidget,
    );
    await tester.tap(find.byKey(const Key('athena-ai-page-refresh')));
    await tester.pumpAndSettle();
    expect(calls, 2);
    expect(find.text('Nueva síntesis verificada'), findsOneWidget);
    expect(find.byKey(const Key('athena-synthesis-provenance')), findsOneWidget);
    expect(find.byKey(const Key('athena-synthesis-advisory-notice')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('ATHENA AI discards late synthesis from a superseded refresh',
      (tester) async {
    final first = Completer<http.Response>();
    final second = Completer<http.Response>();
    var calls = 0;
    final source = AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((_) {
        calls++;
        return calls == 1 ? first.future : second.future;
      }),
    );
    final controller = AthenaSynthesisController(dataSource: source);
    addTearDown(controller.dispose);
    addTearDown(source.dispose);
    await tester.pumpWidget(MaterialApp(home: AthenaAiPage(controller: controller)));
    await tester.pump();
    expect(calls, 1);
    expect(find.byKey(const Key('athena-synthesis-loading')), findsOneWidget);

    await tester.tap(find.byKey(const Key('athena-ai-page-refresh')));
    await tester.pump();
    expect(calls, 2);
    second.complete(http.Response(jsonEncode(_payload('Evidencia reciente')), 200));
    await tester.pumpAndSettle();
    expect(find.text('Evidencia reciente'), findsOneWidget);

    first.complete(http.Response(jsonEncode(_payload('Evidencia obsoleta')), 200));
    await tester.pumpAndSettle();
    expect(find.text('Evidencia reciente'), findsOneWidget);
    expect(find.text('Evidencia obsoleta'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}

Map<String, dynamic> _payload(String summary) => {
      'data': {
        'artifactBindingVerified': true,
        'presentationOnly': true,
        'recommendationInfluence': false,
        'automaticTrading': false,
        'synthesis': {
          'inputFingerprint': 'a' * 64,
          'recommendationInfluence': false,
          'automaticTrading': false,
          'summary': summary,
          'rationale': 'Fuentes contrastadas con límites explícitos.',
          'uncertainties': ['La información puede cambiar.'],
          'evidenceIds': ['news-evidence-1'],
        },
        'provenance': {
          'inputFingerprint': 'a' * 64,
          'news': {
            'artifactHash': 'b' * 64,
            'userFacingTraceability': true,
            'recommendationInfluence': false,
            'automaticTrading': false,
            'assessmentBindings': [
              {
                'evidenceId': 'news-evidence-1',
                'assessmentFingerprint': 'c' * 64,
                'sourceRef': 'https://example.com/news/1',
              },
            ],
          },
        },
      },
    };
