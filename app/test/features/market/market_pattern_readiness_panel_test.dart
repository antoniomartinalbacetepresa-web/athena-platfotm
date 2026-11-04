import 'dart:async';

import 'package:app/features/market/presentation/widgets/market_pattern_readiness_panel.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> _report(String symbol) => {
  'symbol': symbol,
  'status': 'blocked_unverified_market_evidence',
  'licenceVerified': false,
  'historicalPointInTimeEligible': false,
  'patternComputed': false,
  'automaticTrading': false,
  'validDailySessions': 21,
  'invalidOrDuplicateRows': 1,
  'firstObservedDate': '2026-01-01',
  'lastObservedDate': '2026-01-31',
  'latestObservationAgeCalendarDays': 10,
  'checkedAt': '2026-02-10T12:00:00+00:00',
  'sourceProviders': ['provider'],
};

void main() {
  testWidgets('shows coverage and explicitly blocked research, never signals',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: MarketPatternReadinessPanel(
        symbol: 'MSFT',
        load: (symbol) async => _report(symbol),
      )),
    ));
    await tester.tap(find.byKey(const Key('market-pattern-readiness-request')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('market-pattern-readiness-coverage')), findsOneWidget);
    expect(find.textContaining('NO VERIFICADOS'), findsOneWidget);
    expect(find.byKey(const Key('market-pattern-readiness-blocked')), findsOneWidget);
    expect(find.textContaining('No se calculan patrones'), findsOneWidget);
  });

  testWidgets('rejects mismatched provider identity without leaking its payload',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: MarketPatternReadinessPanel(
        symbol: 'MSFT',
        load: (_) async => _report('AAPL'),
      )),
    ));
    await tester.tap(find.byKey(const Key('market-pattern-readiness-request')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('market-pattern-readiness-error')), findsOneWidget);
    expect(find.byKey(const Key('market-pattern-readiness-coverage')), findsNothing);
  });

  testWidgets('stale symbol request cannot overwrite a newly selected company',
      (tester) async {
    final stalled = Completer<Map<String, dynamic>>();
    Future<Map<String, dynamic>> load(String symbol) =>
        symbol == 'MSFT' ? stalled.future : Future.value(_report(symbol));
    Widget page(String symbol) => MaterialApp(
      home: Scaffold(body: MarketPatternReadinessPanel(symbol: symbol, load: load)),
    );
    await tester.pumpWidget(page('MSFT'));
    await tester.tap(find.byKey(const Key('market-pattern-readiness-request')));
    await tester.pump();
    await tester.pumpWidget(page('AAPL'));
    await tester.tap(find.byKey(const Key('market-pattern-readiness-request')));
    await tester.pumpAndSettle();
    expect(find.textContaining('Histórico de AAPL'), findsOneWidget);
    stalled.complete(_report('MSFT'));
    await tester.pump();
    expect(find.textContaining('Histórico de MSFT'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
