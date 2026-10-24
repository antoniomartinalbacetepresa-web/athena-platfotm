import 'dart:convert';

import 'package:app/features/analysis/models/operational_readiness.dart';
import 'package:app/features/analysis/services/athena_readiness_service.dart';
import 'package:app/features/dashboard/presentation/widgets/system_readiness_panel.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

Map<String, dynamic> readinessPayload({int current = 2, bool gatePassed = false}) {
  return {
    'asOf': '2026-10-23T00:00:00+00:00',
    'operationalReadiness': {
      'completionPercent': 71.4,
      'passedGateCount': 5,
      'totalGateCount': 7,
      'ready': false,
      'blockers': ['market_history_depth_insufficient'],
      'gates': [
        {'id': 'market_history_depth', 'passed': gatePassed},
      ],
    },
    'marketHistory': {
      'status': 'diagnostic_only',
      'activeInstrumentCount': 3,
      'historyEligibleInstrumentCount': 3,
      'coveredInstrumentCount': 3,
      'deepHistoryInstrumentCount': 3,
      'currentDeepHistoryInstrumentCount': current,
      'minimumHistoryDays': 365,
      'maximumSourceGapDays': 7,
      'sourceContinuityRequired': true,
      'pointInTimeCutoffApplied': true,
      'productionCoverageClaimed': false,
      'asOf': '2026-10-23T00:00:00+00:00',
    },
  };
}

void main() {
  test('PIT history remains blocked with incomplete current depth', () {
    final report = AthenaReadinessReport.fromMap(readinessPayload());
    expect(report.marketHistory?.eligibleInstrumentCount, 3);
    expect(report.marketHistory?.currentDeepHistoryInstrumentCount, 2);
    expect(report.historyDepthGatePassed, isFalse);
  });

  test('full diagnostic depth requires the explicit backend gate', () {
    final payload = readinessPayload(current: 3);
    expect(AthenaReadinessReport.fromMap(payload).historyDepthGatePassed, isFalse);
    final verified = AthenaReadinessReport.fromMap(
      readinessPayload(current: 3, gatePassed: true),
    );
    expect(verified.historyDepthGatePassed, isTrue);
  });

  test('contradictory counts and missing PIT timezone fail closed', () {
    final payload = readinessPayload(current: 3, gatePassed: true);
    (payload['marketHistory'] as Map<String, dynamic>)['deepHistoryInstrumentCount'] = 2;
    final inconsistent = AthenaReadinessReport.fromMap(payload);
    expect(inconsistent.marketHistory, isNull);
    expect(inconsistent.historyDepthGatePassed, isFalse);

    final naive = readinessPayload(current: 3, gatePassed: true);
    (naive['marketHistory'] as Map<String, dynamic>)['asOf'] =
        '2026-10-23T00:00:00';
    expect(AthenaReadinessReport.fromMap(naive).marketHistory, isNull);
  });

  test('readiness rejects an overall PIT cutoff without timezone', () {
    final payload = readinessPayload(current: 3, gatePassed: true);
    payload['asOf'] = '2026-10-23T00:00:00';
    expect(
      () => AthenaReadinessReport.fromMap(payload),
      throwsFormatException,
    );
  });

  test('history gate fails closed when its PIT cutoff differs from report', () {
    final payload = readinessPayload(current: 3, gatePassed: true);
    (payload['marketHistory'] as Map<String, dynamic>)['asOf'] =
        '2026-10-22T00:00:00+00:00';
    final report = AthenaReadinessReport.fromMap(payload);
    expect(report.marketHistory, isNotNull);
    expect(report.historyDepthGatePassed, isFalse);
  });

  test('equivalent timezone offsets preserve matching PIT instant', () {
    final payload = readinessPayload(current: 3, gatePassed: true);
    (payload['marketHistory'] as Map<String, dynamic>)['asOf'] =
        '2026-10-23T02:00:00+02:00';
    final report = AthenaReadinessReport.fromMap(payload);
    expect(report.historyDepthGatePassed, isTrue);
  });

  testWidgets('Dashboard shows blocked PIT coverage without production claims',
      (tester) async {
    final service = AthenaReadinessService(
      baseUrl: 'https://athena.example',
      client: MockClient((request) async {
        expect(request.url.path, '/api/v1/readiness');
        return http.Response(jsonEncode(readinessPayload()), 200);
      }),
    );
    addTearDown(service.dispose);
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: SizedBox(
          height: 112,
          width: 700,
          child: SystemReadinessPanel(service: service),
        ),
      ),
    ));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('dashboard-market-history-status')),
        findsOneWidget);
    expect(find.textContaining('2/3 vigentes'), findsOneWidget);
    expect(find.textContaining('BLOQUEADO'), findsOneWidget);
    expect(find.textContaining('no producción'), findsOneWidget);
  });

  testWidgets('Dashboard fails closed on 503 and recovers only after retry',
      (tester) async {
    var calls = 0;
    final service = AthenaReadinessService(
      baseUrl: 'https://athena.example',
      client: MockClient((_) async {
        calls++;
        if (calls == 1) return http.Response('unavailable', 503);
        return http.Response(
          jsonEncode(readinessPayload(current: 3, gatePassed: true)),
          200,
        );
      }),
    );
    addTearDown(service.dispose);
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: SizedBox(
          height: 112,
          width: 700,
          child: SystemReadinessPanel(service: service),
        ),
      ),
    ));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('dashboard-market-history-status')),
        findsNothing);
    expect(find.text('READINESS OPERATIVO NO DISPONIBLE'), findsOneWidget);

    await tester.tap(find.byTooltip('Reintentar'));
    await tester.pumpAndSettle();
    expect(calls, 2);
    expect(find.textContaining('3/3 vigentes'), findsOneWidget);
    expect(find.textContaining('gate diagnóstico OK'), findsOneWidget);
    expect(find.textContaining('no producción'), findsOneWidget);
  });
}
