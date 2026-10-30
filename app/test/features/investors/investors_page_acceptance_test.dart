import 'dart:async';

import 'package:app/features/investors/models/relevant_investor_activity.dart';
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

  testWidgets('Session CIK query validates before network and never retains prior evidence',
      (tester) async {
    final requested = <String>[];
    await tester.pumpWidget(MaterialApp(
      home: InvestorsPage(
        configuredCiks: const [],
        loader: (cik) async {
          requested.add(cik);
          throw StateError('private SEC transport token=never-display');
        },
      ),
    ));

    await tester.enterText(
      find.byKey(const Key('investors-cik-input')),
      '123, invalid',
    );
    await tester.tap(find.byKey(const Key('investors-cik-submit')));
    await tester.pumpAndSettle();
    expect(requested, isEmpty);
    expect(find.byKey(const Key('investors-cik-validation-error')), findsOneWidget);
    expect(find.text('Sin inversores configurados'), findsOneWidget);

    await tester.enterText(
      find.byKey(const Key('investors-cik-input')),
      '1, 2, 3, 4, 5, 6',
    );
    await tester.tap(find.byKey(const Key('investors-cik-submit')));
    await tester.pumpAndSettle();
    expect(requested, isEmpty);

    await tester.enterText(
      find.byKey(const Key('investors-cik-input')),
      '123, 123, 456',
    );
    await tester.tap(find.byKey(const Key('investors-cik-submit')));
    await tester.pumpAndSettle();
    expect(requested, ['123', '456']);
    expect(find.byKey(const Key('investors-cik-validation-error')), findsNothing);
    expect(find.text('Actividad no disponible'), findsOneWidget);
    expect(find.textContaining('never-display'), findsNothing);

    await tester.tap(find.byKey(const Key('investors-cik-clear')));
    await tester.pumpAndSettle();
    expect(find.text('Sin inversores configurados'), findsOneWidget);
    expect(find.text('Actividad no disponible'), findsNothing);
    expect(find.textContaining('123'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('Replacing a pending CIK cohort rejects late results from the old query',
      (tester) async {
    final pending = Completer<RelevantInvestorActivity>();
    final requested = <String>[];
    await tester.pumpWidget(MaterialApp(
      home: InvestorsPage(
        configuredCiks: const ['111'],
        loader: (cik) {
          requested.add(cik);
          if (cik == '111') return pending.future;
          return Future<RelevantInvestorActivity>.error(
            StateError('private SEC token=hidden'),
          );
        },
      ),
    ));
    await tester.pump();
    expect(requested, ['111']);

    await tester.enterText(
      find.byKey(const Key('investors-cik-input')),
      '222',
    );
    await tester.tap(find.byKey(const Key('investors-cik-submit')));
    await tester.pumpAndSettle();
    expect(requested, ['111', '222']);
    expect(find.text('Actividad no disponible'), findsOneWidget);
    expect(find.textContaining('hidden'), findsNothing);

    pending.completeError(StateError('old SEC token=stale'));
    await tester.pump();
    expect(find.text('Actividad no disponible'), findsOneWidget);
    expect(find.textContaining('stale'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
