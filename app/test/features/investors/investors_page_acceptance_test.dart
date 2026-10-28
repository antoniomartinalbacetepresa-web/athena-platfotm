import 'package:app/features/investors/presentation/pages/investors_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('Investors route exposes a read-only accessible empty state',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(home: InvestorsPage(configuredCiks: [])),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('investors-page-heading')), findsOneWidget);
    final heading = tester.widget<Semantics>(
      find.ancestor(
        of: find.byKey(const Key('investors-page-heading')),
        matching: find.byType(Semantics),
      ).first,
    );
    expect(heading.properties.header, isTrue);
    expect(find.text('Sin inversores configurados'), findsOneWidget);
    expect(
      find.bySemanticsLabel(
        'Evidencia institucional point-in-time de SEC 13F. Es informativa y separada: no altera el score ATHENA, no genera recomendaciones y no ejecuta órdenes.',
      ),
      findsOneWidget,
    );
  });

  testWidgets('Investors route fails closed and retries without leaking errors',
      (tester) async {
    var requests = 0;
    await tester.pumpWidget(MaterialApp(
      home: InvestorsPage(
        configuredCiks: const ['123456'],
        loader: (_) async {
          requests++;
          throw StateError('private SEC transport token=do-not-display');
        },
      ),
    ));
    await tester.pumpAndSettle();

    expect(requests, 1);
    expect(find.text('Actividad no disponible'), findsOneWidget);
    expect(find.textContaining('do-not-display'), findsNothing);
    expect(find.textContaining('CIK 123456'), findsNothing);

    await tester.tap(find.text('Reintentar'));
    await tester.pumpAndSettle();
    expect(requests, 2);
    expect(find.text('Actividad no disponible'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
