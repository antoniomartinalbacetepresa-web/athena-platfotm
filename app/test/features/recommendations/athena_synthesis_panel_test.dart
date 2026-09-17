import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:athena_tyche/features/recommendations/controllers/athena_synthesis_controller.dart';
import 'package:athena_tyche/features/recommendations/data/datasources/athena_backend_synthesis_data_source.dart';
import 'package:athena_tyche/features/recommendations/presentation/athena_synthesis_panel.dart';

const hash = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

AthenaSynthesisController _controller(http.Client client) => AthenaSynthesisController(
      dataSource: AthenaBackendSynthesisDataSource(baseUrl: 'https://athena.test', client: client),
    );

Map<String, dynamic> _validPayload() => {
      'data': {
        'artifactBindingVerified': true,
        'synthesis': {
          'inputFingerprint': hash,
          'summary': 'El escenario central mantiene crecimiento moderado.',
          'rationale': 'News e Investors coinciden en los riesgos principales.',
          'uncertainties': ['La demanda futura puede desviarse del escenario central.'],
          'evidenceIds': ['news:1', 'investors:1'],
          'recommendationInfluence': false,
          'automaticTrading': false,
        },
        'provenance': {
          'inputFingerprint': hash,
          'news': {
            'artifactHash': hash,
            'artifactType': 'canonical_news_synthesis',
            'assessmentBindings': [
              {'evidenceId': 'news:1', 'assessmentFingerprint': hash, 'sourceRef': 'https://example.com/news/1'}
            ],
            'userFacingTraceability': true,
            'recommendationInfluence': false,
            'automaticTrading': false,
          },
          'investors': {
            'artifactHash': hash,
            'artifactType': 'canonical_investors_synthesis',
            'assessmentBindings': [
              {'evidenceId': 'investors:1', 'assessmentFingerprint': hash, 'sourceRef': 'https://example.com/investors/1'}
            ],
            'userFacingTraceability': true,
            'recommendationInfluence': false,
            'automaticScoring': false,
            'automaticTrading': false,
          },
        },
      }
    };

void main() {
  testWidgets('muestra estado vacío sin fabricar síntesis', (tester) async {
    final controller = _controller(MockClient((_) async => http.Response('{}', 500)));
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: AthenaSynthesisPanel(controller: controller))));
    expect(find.byKey(const Key('athena-synthesis-empty')), findsOneWidget);
    expect(find.byKey(const Key('athena-synthesis-content')), findsNothing);
  });

  testWidgets('presenta síntesis, incertidumbres y provenance verificadas', (tester) async {
    final controller = _controller(MockClient((_) async => http.Response(jsonEncode(_validPayload()), 200)));
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: AthenaSynthesisPanel(controller: controller))));
    await controller.load(hash);
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('athena-synthesis-content')), findsOneWidget);
    expect(find.text('El escenario central mantiene crecimiento moderado.'), findsOneWidget);
    expect(find.text('La demanda futura puede desviarse del escenario central.'), findsOneWidget);
    expect(find.text('News verificada'), findsOneWidget);
    expect(find.text('Investors verificado'), findsOneWidget);
    expect(find.text('2 evidencias'), findsOneWidget);
    expect(find.byKey(const Key('athena-synthesis-advisory-notice')), findsOneWidget);
  });

  testWidgets('un fallo de verificación oculta contenido y ofrece retry', (tester) async {
    var attempts = 0;
    final controller = _controller(MockClient((_) async {
      attempts += 1;
      if (attempts == 1) return http.Response('temporarily unavailable', 503);
      return http.Response(jsonEncode(_validPayload()), 200);
    }));
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: AthenaSynthesisPanel(controller: controller))));
    await controller.load(hash);
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('athena-synthesis-error')), findsOneWidget);
    expect(find.byKey(const Key('athena-synthesis-content')), findsNothing);

    await tester.tap(find.byKey(const Key('athena-synthesis-retry')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('athena-synthesis-content')), findsOneWidget);
    expect(attempts, 2);
  });
}
