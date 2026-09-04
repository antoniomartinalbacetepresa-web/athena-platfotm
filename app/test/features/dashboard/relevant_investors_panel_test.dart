import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/dashboard/presentation/widgets/relevant_investors_panel.dart';
import 'package:app/features/investors/models/relevant_investor_activity.dart';

RelevantInvestorActivity activityFor(String cik) {
  return RelevantInvestorActivity(
    cik: cik,
    form: '13F-HR',
    accessionNumber: '0000123456-26-000001',
    positionDate: DateTime.utc(2026, 6, 30),
    filingDate: DateTime.utc(2026, 8, 14),
    publicationDateTime: DateTime.utc(2026, 8, 14, 20, 30),
    retrievedAt: DateTime.utc(2026, 9, 4, 20),
    sourceUrl:
        'https://www.sec.gov/Archives/edgar/data/123456/000012345626000001/table.xml',
    sourceProvider: 'SEC EDGAR',
    valueUnit: 'thousands_usd_as_reported_by_sec_13f',
    holdings: const [
      RelevantInvestorHolding(
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
}
