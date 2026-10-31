import 'package:app/features/dashboard/presentation/widgets/relevant_investors_panel.dart';
import 'package:app/features/investors/models/relevant_investor_activity.dart';
import 'package:app/features/investors/models/sec_13f_overlap.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

RelevantInvestorHolding holding(
  String cusip, {
  String type = 'SH',
  String? option,
}) =>
    RelevantInvestorHolding(
      issuerName: 'SEC REPORTED ISSUER',
      titleOfClass: 'COM',
      cusip: cusip,
      valueThousandsUsd: 100,
      shareOrPrincipalAmount: 1000,
      shareOrPrincipalType: type,
      putCall: option,
      investmentDiscretion: 'SOLE',
      votingSole: 1000,
      votingShared: 0,
      votingNone: 0,
    );

RelevantInvestorActivity filing(
  String cik,
  List<RelevantInvestorHolding> holdings, {
  int day = 30,
  String form = '13F-HR',
}) =>
    RelevantInvestorActivity(
      cik: cik,
      form: form,
      accessionNumber: '0000123456-26-000001',
      positionDate: DateTime.utc(2026, 6, day),
      filingDate: DateTime.utc(2026, 8, 14),
      publicationDateTime: DateTime.utc(2026, 8, 14, 20, 30),
      retrievedAt: DateTime.utc(2026, 9, 4, 20),
      sourceUrl:
          'https://www.sec.gov/Archives/edgar/data/123456/000012345626000001/table.xml',
      sourceProvider: 'SEC EDGAR',
      valueUnit: 'thousands_usd_as_reported_by_sec_13f',
      holdings: holdings,
    );

void main() {
  test('counts each CIK once per exact CUSIP and orders by manager count', () {
    final report = Sec13fOverlapReport.fromFilings([
      filing('111', [holding('037833100'), holding('037833100'), holding('594918104')]),
      filing('222', [holding('037833100'), holding('594918104')]),
      filing('333', [holding('037833100')]),
    ]);
    expect(report, isNotNull);
    expect(report!.managerCount, 3);
    expect(report.sharedCusips.map((entry) => entry.cusip),
        ['037833100', '594918104']);
    expect(report.sharedCusips.first.ciks, ['111', '222', '333']);
    expect(report.sharedCusips.last.ciks, ['111', '222']);
  });

  test('refuses mismatched reporting dates, amendments and duplicate managers', () {
    final normal = filing('111', [holding('037833100')]);
    expect(Sec13fOverlapReport.fromFilings([
      normal, filing('222', [holding('037833100')], day: 29),
    ]), isNull);
    expect(Sec13fOverlapReport.fromFilings([
      normal, filing('222', [holding('037833100')], form: '13F-HR/A'),
    ]), isNull);
    expect(Sec13fOverlapReport.fromFilings([normal, normal]), isNull);
    expect(Sec13fOverlapReport.fromFilings([normal]), isNull);
  });

  test('rejects aliases of the same SEC CIK as two independent managers', () {
    final report = Sec13fOverlapReport.fromFilings([
      filing('0000000111', [holding('037833100')]),
      filing('111', [holding('037833100')]),
    ]);
    expect(report, isNull);
    expect(Sec13fOverlapReport.fromFilings([
      filing('0', [holding('037833100')]),
      filing('222', [holding('037833100')]),
    ]), isNull);
  });

  test('does not count options, principal rows or placeholder CUSIPs', () {
    final report = Sec13fOverlapReport.fromFilings([
      filing('111', [
        holding('037833100'),
        holding('594918104', option: 'PUT'),
        holding('123456789', type: 'PRN'),
        holding('12345@789'),
      ]),
      filing('222', [
        holding('037833100'),
        holding('594918104'),
        holding('123456789'),
        holding('12345@789'),
      ]),
    ]);
    expect(report, isNotNull);
    expect(report!.sharedCusips.map((entry) => entry.cusip), ['037833100']);
  });

  testWidgets('shows real same-period overlap with read-only complete details',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: SizedBox(
          width: 900,
          height: 600,
          child: RelevantInvestorsPanel(
            configuredCiks: const ['111', '222'],
            loader: (cik) async => filing(cik, [
              holding('037833100'),
              holding(cik == '111' ? '594918104' : '123456789'),
            ]),
          ),
        ),
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('investor-overlap-summary')), findsOneWidget);
    expect(find.textContaining('1 CUSIP coincidente'), findsOneWidget);
    await tester.tap(find.byKey(const Key('investor-overlap-detail')));
    await tester.pumpAndSettle();
    expect(find.text('CUSIP 037833100'), findsOneWidget);
    expect(find.textContaining('CIK 111, 222'), findsOneWidget);
    expect(find.textContaining('No son posiciones actuales'), findsOneWidget);
  });
}
