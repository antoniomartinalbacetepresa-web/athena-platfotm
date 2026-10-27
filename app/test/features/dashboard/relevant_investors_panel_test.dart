import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/dashboard/presentation/widgets/relevant_investors_panel.dart';
import 'package:app/features/investors/models/relevant_investor_activity.dart';

RelevantInvestorActivity activityFor(
  String cik, {
  List<RelevantInvestorHolding> extraHoldings = const [],
  String form = '13F-HR',
}) {
  return RelevantInvestorActivity(
    cik: cik,
    form: form,
    accessionNumber: '0000123456-26-000001',
    positionDate: DateTime.utc(2026, 6, 30),
    filingDate: DateTime.utc(2026, 8, 14),
    publicationDateTime: DateTime.utc(2026, 8, 14, 20, 30),
    retrievedAt: DateTime.utc(2026, 9, 4, 20),
    sourceUrl:
        'https://www.sec.gov/Archives/edgar/data/123456/000012345626000001/table.xml',
    sourceProvider: 'SEC EDGAR',
    valueUnit: 'thousands_usd_as_reported_by_sec_13f',
    holdings: [
      const RelevantInvestorHolding(
        issuerName: 'APPLE INC',
        titleOfClass: 'COM',
        cusip: '037833100',
        valueThousandsUsd: 123456,
        shareOrPrincipalAmount: 500000,
        shareOrPrincipalType: 'SH',
        putCall: null,
        investmentDiscretion: 'SOLE',
        votingSole: 500000,
        votingShared: 0,
        votingNone: 0,
      ),
      ...extraHoldings,
    ],
  );
}

Widget host(Widget child) {
  return MaterialApp(
    home: Scaffold(
      body: SizedBox(width: 900, height: 500, child: child),
    ),
  );
}

void main() {
  testWidgets('shows no fabricated investor when no CIK is configured', (
    tester,
  ) async {
    var calls = 0;
    await tester.pumpWidget(
      host(
        RelevantInvestorsPanel(
          configuredCiks: const [],
          loader: (cik) async {
            calls += 1;
            return activityFor(cik);
          },
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Sin inversores configurados'), findsOneWidget);
    expect(find.textContaining('evidencia 13F real'), findsOneWidget);
    expect(calls, 0);
  });

  testWidgets('renders SEC evidence with distinct PIT dates and no score claim', (
    tester,
  ) async {
    await tester.pumpWidget(
      host(
        RelevantInvestorsPanel(
          configuredCiks: const ['123456'],
          loader: (cik) async => activityFor(cik),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('CIK 123456'), findsOneWidget);
    expect(find.textContaining('Posición 2026-06-30'), findsOneWidget);
    expect(find.textContaining('filing 2026-08-14'), findsOneWidget);
    expect(find.textContaining('Publicado 2026-08-14 20:30 UTC'), findsOneWidget);
    expect(find.textContaining('recuperado 2026-09-04 20:00 UTC'), findsOneWidget);
    expect(find.textContaining('APPLE INC · CUSIP 037833100'), findsOneWidget);
    expect(
      find.textContaining('evidencia separada; no altera el score ATHENA'),
      findsOneWidget,
    );
    expect(find.textContaining('AAPL'), findsNothing);
  });

  testWidgets('deduplicates configured CIKs before loading', (tester) async {
    var calls = 0;
    await tester.pumpWidget(
      host(
        RelevantInvestorsPanel(
          configuredCiks: const ['123456', ' 123456 ', ''],
          loader: (cik) async {
            calls += 1;
            return activityFor(cik);
          },
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(calls, 1);
    expect(find.textContaining('CIK 123456'), findsOneWidget);
  });

  testWidgets('invalid CIK configuration fails closed without network loading', (
    tester,
  ) async {
    var calls = 0;
    await tester.pumpWidget(
      host(
        RelevantInvestorsPanel(
          configuredCiks: const ['123456', 'bad-cik'],
          loader: (cik) async {
            calls += 1;
            return activityFor(cik);
          },
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Configuración institucional inválida'), findsOneWidget);
    expect(find.textContaining('lista de CIKs no es verificable'), findsOneWidget);
    expect(calls, 0);
    expect(find.textContaining('CIK 123456'), findsNothing);
  });

  testWidgets('fails closed when any configured investor cannot be verified', (
    tester,
  ) async {
    await tester.pumpWidget(
      host(
        RelevantInvestorsPanel(
          configuredCiks: const ['123456', '999999'],
          loader: (cik) async {
            if (cik == '999999') {
              throw const FormatException('invalid provenance');
            }
            return activityFor(cik);
          },
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Actividad no disponible'), findsOneWidget);
    expect(find.textContaining('CIK 123456'), findsNothing);
  });
  testWidgets('reconfiguring CIKs drops pending evidence from old cohort',
      (tester) async {
    final pending = Completer<RelevantInvestorActivity>();
    Future<RelevantInvestorActivity> loader(String cik) =>
        cik == '123456' ? pending.future : Future.value(activityFor(cik));

    await tester.pumpWidget(host(RelevantInvestorsPanel(
      configuredCiks: const ['123456'],
      loader: loader,
    )));
    await tester.pump();
    await tester.pumpWidget(host(RelevantInvestorsPanel(
      configuredCiks: const ['999999'],
      loader: loader,
    )));
    await tester.pumpAndSettle();
    expect(find.textContaining('CIK 999999'), findsOneWidget);
    expect(find.textContaining('CIK 123456'), findsNothing);
    pending.complete(activityFor('123456'));
    await tester.pump();
    expect(find.textContaining('CIK 999999'), findsOneWidget);
    expect(find.textContaining('CIK 123456'), findsNothing);
  });

  testWidgets('invalid CIK configuration recovers after live correction',
      (tester) async {
    var calls = 0;
    Future<RelevantInvestorActivity> loader(String cik) async {
      calls++;
      return activityFor(cik);
    }
    await tester.pumpWidget(host(RelevantInvestorsPanel(
      configuredCiks: const ['bad-cik'],
      loader: loader,
    )));
    await tester.pumpAndSettle();
    expect(find.text('Configuración institucional inválida'), findsOneWidget);
    expect(calls, 0);
    await tester.pumpWidget(host(RelevantInvestorsPanel(
      configuredCiks: const ['123456'],
      loader: loader,
    )));
    await tester.pumpAndSettle();
    expect(find.textContaining('CIK 123456'), findsOneWidget);
    expect(calls, 1);
  });

  testWidgets('changing loader rebinds same CIK and rejects stale response',
      (tester) async {
    final pending = Completer<RelevantInvestorActivity>();
    var newCalls = 0;
    Future<RelevantInvestorActivity> oldLoader(String cik) => pending.future;
    Future<RelevantInvestorActivity> newLoader(String cik) async {
      newCalls++;
      return activityFor(cik);
    }
    await tester.pumpWidget(host(RelevantInvestorsPanel(
      configuredCiks: const ['123456'],
      loader: oldLoader,
    )));
    await tester.pump();
    await tester.pumpWidget(host(RelevantInvestorsPanel(
      configuredCiks: const ['123456'],
      loader: newLoader,
    )));
    await tester.pumpAndSettle();
    expect(newCalls, 1);
    expect(find.textContaining('CIK 123456'), findsOneWidget);
    pending.complete(activityFor('123456'));
    await tester.pump();
    expect(find.textContaining('CIK 123456'), findsOneWidget);
  });

  testWidgets('mismatched CIK returned by loader is never displayed',
      (tester) async {
    await tester.pumpWidget(host(RelevantInvestorsPanel(
      configuredCiks: const ['123456'],
      loader: (_) async => activityFor('999999'),
    )));
    await tester.pumpAndSettle();
    expect(find.text('Actividad no disponible'), findsOneWidget);
    expect(find.textContaining('CIK 999999'), findsNothing);
  });


  testWidgets('opens complete SEC 13F holdings without presenting them as current',
      (tester) async {
    const additional = [
      RelevantInvestorHolding(
        issuerName: 'SECOND ISSUER',
        titleOfClass: 'COM',
        cusip: '123456789',
        valueThousandsUsd: 200,
        shareOrPrincipalAmount: 10,
        shareOrPrincipalType: 'SH',
        putCall: null,
        investmentDiscretion: 'SOLE',
        votingSole: 10,
        votingShared: 0,
        votingNone: 0,
      ),
      RelevantInvestorHolding(
        issuerName: 'THIRD ISSUER',
        titleOfClass: 'COM',
        cusip: '987654321',
        valueThousandsUsd: 100,
        shareOrPrincipalAmount: 5,
        shareOrPrincipalType: 'SH',
        putCall: null,
        investmentDiscretion: 'SOLE',
        votingSole: 5,
        votingShared: 0,
        votingNone: 0,
      ),
    ];
    await tester.pumpWidget(host(RelevantInvestorsPanel(
      configuredCiks: const ['123456'],
      loader: (cik) async => activityFor(cik, extraHoldings: additional),
    )));
    await tester.pumpAndSettle();
    expect(find.text('THIRD ISSUER'), findsNothing);
    await tester.tap(find.text('Ver todas las posiciones (3)'));
    await tester.pumpAndSettle();
    // The details use a lazy list; later SEC holdings require scrolling.
    await tester.scrollUntilVisible(
      find.text('THIRD ISSUER'),
      120,
      scrollable: find.descendant(
        of: find.byKey(const Key('investor-holdings-detail-list')),
        matching: find.byType(Scrollable),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('THIRD ISSUER'), findsOneWidget);
    expect(find.textContaining('no representan posiciones actuales'), findsOneWidget);
    expect(find.textContaining('expediente 0000123456-26-000001'), findsOneWidget);
    expect(find.textContaining('CUSIP 987654321'), findsOneWidget);
    await tester.tap(find.byTooltip('Cerrar detalle 13F'));
    await tester.pumpAndSettle();
    expect(find.text('THIRD ISSUER'), findsNothing);
  });

  testWidgets('single holding detail preserves SEC source and historical dates',
      (tester) async {
    await tester.pumpWidget(host(RelevantInvestorsPanel(
      configuredCiks: const ['123456'],
      loader: (cik) async => activityFor(cik),
    )));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Ver todas las posiciones (1)'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Posición 2026-06-30'), findsWidgets);
    expect(find.textContaining('publicado 2026-08-14 20:30 UTC'), findsOneWidget);
    expect(find.textContaining('www.sec.gov/Archives/edgar/data/123456'), findsWidgets);
    expect(find.textContaining('no representan posiciones actuales'), findsOneWidget);
    expect(find.textContaining('AAPL'), findsNothing);
  });
  testWidgets('filters all reported holdings by issuer and CUSIP, with recovery',
      (tester) async {
    const additional = [
      RelevantInvestorHolding(
        issuerName: 'THIRD ISSUER',
        titleOfClass: 'COM',
        cusip: '987654321',
        valueThousandsUsd: 100,
        shareOrPrincipalAmount: 5,
        shareOrPrincipalType: 'SH',
        putCall: null,
        investmentDiscretion: 'SOLE',
        votingSole: 5,
        votingShared: 0,
        votingNone: 0,
      ),
      RelevantInvestorHolding(
        issuerName: 'FOURTH ISSUER',
        titleOfClass: 'COM',
        cusip: '123456789',
        valueThousandsUsd: 200,
        shareOrPrincipalAmount: 10,
        shareOrPrincipalType: 'SH',
        putCall: null,
        investmentDiscretion: 'SOLE',
        votingSole: 10,
        votingShared: 0,
        votingNone: 0,
      ),
    ];
    await tester.pumpWidget(host(RelevantInvestorsPanel(
      configuredCiks: const ['123456'],
      loader: (cik) async => activityFor(cik, extraHoldings: additional),
    )));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Ver todas las posiciones (3)'));
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byKey(const Key('investor-holdings-search')), 'third',
    );
    await tester.pumpAndSettle();
    expect(find.text('THIRD ISSUER'), findsOneWidget);
    expect(find.text('APPLE INC'), findsNothing);
    expect(find.text('1 de 3 posiciones'), findsOneWidget);
    expect(find.textContaining('no representan posiciones actuales'), findsOneWidget);

    await tester.enterText(
      find.byKey(const Key('investor-holdings-search')), '123456789',
    );
    await tester.pumpAndSettle();
    expect(find.text('FOURTH ISSUER'), findsOneWidget);
    expect(find.text('THIRD ISSUER'), findsNothing);

    await tester.enterText(
      find.byKey(const Key('investor-holdings-search')), 'not-present',
    );
    await tester.pumpAndSettle();
    expect(find.text('Sin coincidencias en este expediente 13F'), findsOneWidget);
    expect(find.text('0 de 3 posiciones'), findsOneWidget);

    await tester.tap(find.byTooltip('Limpiar búsqueda 13F'));
    await tester.pumpAndSettle();
    expect(find.text('3 de 3 posiciones'), findsOneWidget);
    expect(find.text('APPLE INC'), findsOneWidget);
  });

  testWidgets('sorts by declared value without losing SEC document order',
      (tester) async {
    const larger = RelevantInvestorHolding(
      issuerName: 'LARGER ISSUER',
      titleOfClass: 'COM',
      cusip: '123456789',
      valueThousandsUsd: 200000,
      shareOrPrincipalAmount: 10,
      shareOrPrincipalType: 'SH',
      putCall: null,
      investmentDiscretion: 'SOLE',
      votingSole: 10,
      votingShared: 0,
      votingNone: 0,
    );
    await tester.pumpWidget(host(RelevantInvestorsPanel(
      configuredCiks: const ['123456'],
      loader: (cik) async => activityFor(cik, extraHoldings: const [larger]),
    )));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Ver todas las posiciones (2)'));
    await tester.pumpAndSettle();

    Finder rows() => find.descendant(
      of: find.byKey(const Key('investor-holdings-detail-list')),
      matching: find.byType(ListTile),
    );
    expect((tester.widget<ListTile>(rows().first).title as Text).data, 'APPLE INC');
    await tester.tap(find.byKey(const Key('investor-holdings-sort')));
    await tester.pumpAndSettle();
    expect((tester.widget<ListTile>(rows().first).title as Text).data, 'LARGER ISSUER');
    expect(find.text('Orden: valor declarado ↓'), findsOneWidget);
    await tester.tap(find.byKey(const Key('investor-holdings-sort')));
    await tester.pumpAndSettle();
    expect((tester.widget<ListTile>(rows().first).title as Text).data, 'APPLE INC');
  });


  testWidgets('SEC 13F summary separates ordinary, PUT and CALL reported values',
      (tester) async {
    const options = [
      RelevantInvestorHolding(
        issuerName: 'PUT ISSUER',
        titleOfClass: 'COM',
        cusip: '123456789',
        valueThousandsUsd: 200,
        shareOrPrincipalAmount: 10,
        shareOrPrincipalType: 'SH',
        putCall: 'PUT',
        investmentDiscretion: 'SOLE',
        votingSole: 0,
        votingShared: 0,
        votingNone: 0,
      ),
      RelevantInvestorHolding(
        issuerName: 'CALL ISSUER',
        titleOfClass: 'COM',
        cusip: '987654321',
        valueThousandsUsd: 300,
        shareOrPrincipalAmount: 5,
        shareOrPrincipalType: 'SH',
        putCall: 'CALL',
        investmentDiscretion: 'SOLE',
        votingSole: 0,
        votingShared: 0,
        votingNone: 0,
      ),
    ];
    await tester.pumpWidget(host(RelevantInvestorsPanel(
      configuredCiks: const ['123456'],
      loader: (cik) async => activityFor(cik, extraHoldings: options),
    )));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Ver todas las posiciones (3)'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('investor-filing-summary')));
    await tester.pumpAndSettle();
    expect(find.text('Suma de valores declarados: 123956 miles USD'),
        findsOneWidget);
    expect(find.text('Sin opción: 123456 miles USD'), findsOneWidget);
    expect(find.text('PUT: 200 miles USD'), findsOneWidget);
    expect(find.text('CALL: 300 miles USD'), findsOneWidget);
    expect(find.textContaining('no una cartera completa'), findsOneWidget);
    expect(find.textContaining('Fuente: https://www.sec.gov/'), findsOneWidget);
    await tester.tap(find.text('Cerrar resumen'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('investor-holdings-search')), findsOneWidget);
  });

  testWidgets('13F amendment is never described as a complete current portfolio',
      (tester) async {
    await tester.pumpWidget(host(RelevantInvestorsPanel(
      configuredCiks: const ['123456'],
      loader: (cik) async => activityFor(cik, form: '13F-HR/A'),
    )));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Ver todas las posiciones (1)'));
    await tester.pumpAndSettle();
    expect(find.textContaining('puede contener solo parte'), findsOneWidget);
    await tester.tap(find.byKey(const Key('investor-filing-summary')));
    await tester.pumpAndSettle();
    expect(find.textContaining('puede modificar solo parte'), findsOneWidget);
    expect(find.textContaining('No se interpreta como cartera completa'),
        findsOneWidget);
  });

  testWidgets('SEC 13F loading and failure announce status and retry restores verified evidence',
      (tester) async {
    final pending = Completer<RelevantInvestorActivity>();
    var calls = 0;
    await tester.pumpWidget(host(RelevantInvestorsPanel(
      configuredCiks: const ['123456'],
      loader: (cik) {
        calls++;
        return calls == 1 ? pending.future : Future.value(activityFor(cik));
      },
    )));
    await tester.pump();

    expect(
      find.byWidgetPredicate((widget) =>
          widget is Semantics &&
          widget.properties.liveRegion == true &&
          widget.properties.label == 'Consultando actividad institucional SEC 13F.'),
      findsOneWidget,
    );
    pending.completeError(const FormatException('unverified SEC source'));
    await tester.pumpAndSettle();
    expect(find.text('Actividad no disponible'), findsOneWidget);
    expect(
      find.byWidgetPredicate((widget) =>
          widget is Semantics &&
          widget.properties.liveRegion == true &&
          widget.properties.label!.startsWith('Actividad no disponible.')),
      findsOneWidget,
    );
    expect(find.textContaining('CIK 123456'), findsNothing);

    await tester.tap(find.text('Reintentar'));
    await tester.pumpAndSettle();
    expect(calls, 2);
    expect(find.textContaining('CIK 123456'), findsOneWidget);
    expect(find.text('Actividad no disponible'), findsNothing);
  });

  testWidgets('SEC 13F exposes and copies original filing provenance without advice',
      (tester) async {
    const url =
        'https://www.sec.gov/Archives/edgar/data/123456/000012345626000001/table.xml';
    String? copied;
    final messenger = TestDefaultBinaryMessengerBinding
        .instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') {
        copied = (call.arguments as Map)['text'] as String;
      }
      return null;
    });
    addTearDown(() =>
        messenger.setMockMethodCallHandler(SystemChannels.platform, null));

    await tester.pumpWidget(host(RelevantInvestorsPanel(
      configuredCiks: const ['123456'],
      loader: (cik) async => activityFor(cik),
    )));
    await tester.pumpAndSettle();

    expect(find.text(url), findsOneWidget);
    expect(
      find.byWidgetPredicate((widget) =>
          widget is Semantics &&
          widget.properties.label == 'Fuente SEC 13F verificada: $url'),
      findsOneWidget,
    );
    expect(find.byKey(const Key('investor-copy-filing-123456')),
        findsOneWidget);
    await tester.tap(find.byTooltip('Copiar enlace SEC 13F de CIK 123456'));
    await tester.pump();
    expect(copied, url);
    expect(find.text('Enlace SEC 13F copiado'), findsOneWidget);
    expect(find.textContaining('no altera el score ATHENA'), findsWidgets);
    expect(tester.takeException(), isNull);
  });

  testWidgets('failed SEC refresh hides filing link until verified retry',
      (tester) async {
    var calls = 0;
    final failedRefresh = Completer<RelevantInvestorActivity>();
    await tester.pumpWidget(host(RelevantInvestorsPanel(
      configuredCiks: const ['123456'],
      loader: (cik) {
        calls++;
        return calls == 2
            ? failedRefresh.future
            : Future.value(activityFor(cik));
      },
    )));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('investor-copy-filing-123456')),
        findsOneWidget);

    await tester.tap(find.byTooltip('Actualizar actividad SEC 13F'));
    await tester.pump();
    expect(find.byKey(const Key('investor-copy-filing-123456')), findsNothing);
    failedRefresh.completeError(StateError('SEC temporarily unavailable'));
    await tester.pumpAndSettle();
    expect(find.text('Actividad no disponible'), findsOneWidget);
    expect(find.byKey(const Key('investor-copy-filing-123456')), findsNothing);

    await tester.tap(find.text('Reintentar'));
    await tester.pumpAndSettle();
    expect(calls, 3);
    expect(find.text('Actividad no disponible'), findsNothing);
    expect(find.byKey(const Key('investor-copy-filing-123456')),
        findsOneWidget);
  });


  testWidgets('SEC 13F timeout fails closed and retry restores verified filing',
      (tester) async {
    final stalled = Completer<RelevantInvestorActivity>();
    var calls = 0;
    await tester.pumpWidget(host(RelevantInvestorsPanel(
      configuredCiks: const ['123456'],
      loader: (cik) {
        calls++;
        if (calls == 1) {
          return stalled.future.timeout(const Duration(milliseconds: 30));
        }
        return Future.value(activityFor(cik));
      },
    )));
    await tester.pump(const Duration(milliseconds: 40));
    await tester.pump();

    expect(find.text('Actividad no disponible'), findsOneWidget);
    expect(find.textContaining('CIK 123456'), findsNothing);
    await tester.tap(find.text('Reintentar'));
    await tester.pumpAndSettle();

    expect(calls, 2);
    expect(find.textContaining('CIK 123456'), findsOneWidget);
    expect(find.textContaining('evidencia separada; no altera el score ATHENA'),
        findsOneWidget);
  });
}
