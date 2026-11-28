import 'dart:convert';

import 'package:app/features/analysis/models/market_history_coverage.dart';
import 'package:app/features/analysis/services/athena_readiness_service.dart';
import 'package:app/features/dashboard/presentation/widgets/system_readiness_panel.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

final _cutoff = DateTime.parse('2026-10-23T00:00:00+00:00');

Map<String, dynamic> _readiness() => {
      'asOf': '2026-10-23T00:00:00+00:00',
      'operationalReadiness': {
        'completionPercent': 50.0,
        'passedGateCount': 1,
        'totalGateCount': 2,
        'ready': false,
        'blockers': ['market_history_depth_insufficient'],
        'gates': [
          {'id': 'market_history_depth', 'passed': false},
        ],
      },
      'marketHistory': {
        'status': 'diagnostic_only',
        'activeInstrumentCount': 3,
        'historyEligibleInstrumentCount': 3,
        'coveredInstrumentCount': 2,
        'deepHistoryInstrumentCount': 1,
        'currentDeepHistoryInstrumentCount': 1,
        'minimumHistoryDays': 365,
        'maximumSourceGapDays': 7,
        'sourceContinuityRequired': true,
        'pointInTimeCutoffApplied': true,
        'productionCoverageClaimed': false,
        'asOf': '2026-10-23T00:00:00+00:00',
      },
    };

Map<String, dynamic> _coverage() => {
      'status': 'diagnostic_only',
      'asOf': '2026-10-23T00:00:00+00:00',
      'activeInstrumentCount': 3,
      'historyEligibleInstrumentCount': 3,
      'coveredInstrumentCount': 2,
      'deepHistoryInstrumentCount': 1,
      'currentDeepHistoryInstrumentCount': 1,
      'observationCount': 6,
      'instrumentCoverage': 2 / 3,
      'deepHistoryCoverage': 1 / 3,
      'currentDeepHistoryCoverage': 1 / 3,
      'minimumHistoryDays': 365,
      'minimumDeepHistoryCoverage': 1.0,
      'maximumSourceGapDays': 7,
      'sourceContinuityRequired': true,
      'pointInTimeCutoffApplied': true,
      'productionCoverageClaimed': false,
      'historyDepthReady': false,
      'currentHistoryDepthReady': false,
      'earliestObservedAt': '2026-10-01T00:00:00+00:00',
      'latestObservedAt': '2026-10-22T00:00:00+00:00',
      'bySource': {
        'yahoo': {
          'observationCount': 6,
          'coveredInstrumentCount': 2,
          'earliestObservedAt': '2026-10-01T00:00:00+00:00',
          'latestObservedAt': '2026-10-22T00:00:00+00:00',
        },
      },
    };

Future<void> _mount(WidgetTester tester, AthenaReadinessService service) async {
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
}

void main() {
  test('persisted PIT coverage rejects fabricated and inconsistent evidence', () {
    final valid = MarketHistoryCoverage.fromMap(_coverage(), expectedAsOf: _cutoff);
    expect(valid.current, 1);
    expect(valid.observations, 6);

    for (final mutation in <void Function(Map<String, dynamic>)>[
      (map) => map['productionCoverageClaimed'] = true,
      (map) => map['asOf'] = '2026-10-24T00:00:00+00:00',
      (map) => map['currentDeepHistoryInstrumentCount'] = 3,
      (map) => map['currentDeepHistoryCoverage'] = 0.8,
      (map) => map['minimumDeepHistoryCoverage'] = 0.5,
      (map) => map['currentHistoryDepthReady'] = true,
      (map) => map['observationCount'] = 7,
      (map) => map['latestObservedAt'] = '2026-10-24T00:00:00+00:00',
    ]) {
      final payload = _coverage();
      mutation(payload);
      expect(
        () => MarketHistoryCoverage.fromMap(payload, expectedAsOf: _cutoff),
        throwsFormatException,
      );
    }
  });

  testWidgets('Dashboard measures persisted coverage at the same PIT instant',
      (tester) async {
    final requests = <Uri>[];
    final service = AthenaReadinessService(
      baseUrl: 'https://athena.example',
      client: MockClient((request) async {
        if (request.url.path == '/api/v1/readiness') {
          return http.Response(jsonEncode(_readiness()), 200);
        }
        requests.add(request.url);
        return http.Response(jsonEncode(_coverage()), 200);
      }),
    );
    addTearDown(service.dispose);
    await _mount(tester, service);
    await tester.tap(find.byTooltip('Ver cobertura histórica persistida'));
    await tester.pumpAndSettle();
    expect(requests, hasLength(1));
    expect(requests.single.path, '/api/v1/readiness/market-history/coverage');
    expect(DateTime.parse(requests.single.queryParameters['asOf']!)
        .isAtSameMomentAs(_cutoff), isTrue);
    expect(find.byKey(const Key('persisted-current-history-coverage')),
        findsOneWidget);
    expect(find.text('yahoo: 6 observaciones'), findsOneWidget);
    expect(find.textContaining('No acredita cobertura productiva'), findsOneWidget);
  });

  testWidgets('503 fails closed and retry restores only validated coverage',
      (tester) async {
    var attempts = 0;
    final service = AthenaReadinessService(
      baseUrl: 'https://athena.example',
      client: MockClient((request) async {
        if (request.url.path == '/api/v1/readiness') {
          return http.Response(jsonEncode(_readiness()), 200);
        }
        attempts++;
        if (attempts == 1) return http.Response('unavailable', 503);
        return http.Response(jsonEncode(_coverage()), 200);
      }),
    );
    addTearDown(service.dispose);
    await _mount(tester, service);
    await tester.tap(find.byTooltip('Ver cobertura histórica persistida'));
    await tester.pumpAndSettle();
    expect(find.text('Cobertura PIT no disponible.'), findsOneWidget);
    expect(find.byKey(const Key('persisted-current-history-coverage')), findsNothing);
    await tester.tap(find.text('Reintentar cobertura'));
    await tester.pumpAndSettle();
    expect(attempts, 2);
    expect(find.byKey(const Key('persisted-current-history-coverage')),
        findsOneWidget);
  });

  testWidgets('cross-endpoint coverage mismatch blocks the measurement',
      (tester) async {
    final service = AthenaReadinessService(
      baseUrl: 'https://athena.example',
      client: MockClient((request) async {
        if (request.url.path == '/api/v1/readiness') {
          return http.Response(jsonEncode(_readiness()), 200);
        }
        final payload = _coverage();
        payload['historyEligibleInstrumentCount'] = 4;
        payload['activeInstrumentCount'] = 4;
        payload['instrumentCoverage'] = 0.5;
        payload['deepHistoryCoverage'] = 0.25;
        payload['currentDeepHistoryCoverage'] = 0.25;
        return http.Response(jsonEncode(payload), 200);
      }),
    );
    addTearDown(service.dispose);
    await _mount(tester, service);
    await tester.tap(find.byTooltip('Ver cobertura histórica persistida'));
    await tester.pumpAndSettle();
    expect(find.textContaining('no coincide con readiness'), findsOneWidget);
    expect(find.byKey(const Key('persisted-current-history-coverage')),
        findsNothing);
  });
}
