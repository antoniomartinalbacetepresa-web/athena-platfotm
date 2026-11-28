import 'package:app/features/news/presentation/news_synthesis_controller.dart';
import 'package:app/features/news/presentation/widgets/news_synthesis_panel.dart';
import 'package:app/features/news/services/athena_backend_news_synthesis_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  testWidgets('unavailable canonical synthesis is announced and remains retryable',
      (tester) async {
    final service = AthenaBackendNewsSynthesisService(
      baseUrl: 'http://athena.local',
      client: MockClient(
        (_) async => http.Response('{"detail":"unavailable"}', 503),
      ),
    );
    final controller = NewsSynthesisController(service: service);
    await controller.load();

    await tester.pumpWidget(
      MaterialApp(home: Scaffold(body: NewsSynthesisPanel(controller: controller))),
    );

    final status = find.byKey(const Key('news-synthesis-error-status'));
    expect(status, findsOneWidget);
    final semantics = tester.widget<Semantics>(
      find.descendant(of: status, matching: find.byType(Semantics)).first,
    );
    expect(semantics.properties.liveRegion, isTrue);
    expect(
      semantics.properties.label,
      'Error: la síntesis verificada de noticias no está disponible.',
    );
    expect(find.text('Reintentar'), findsOneWidget);
    expect(find.textContaining('ANÁLISIS ATHENA'), findsNothing);

    controller.dispose();
    service.dispose();
  });
}
