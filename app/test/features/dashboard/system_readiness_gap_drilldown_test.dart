import 'dart:convert';

import 'package:app/features/analysis/models/market_history_gaps.dart';
import 'package:app/features/analysis/services/athena_readiness_service.dart';
import 'package:app/features/dashboard/presentation/widgets/system_readiness_panel.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

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
        'activeInstrumentCount': 2,
        'historyEligibleInstrumentCount': 2,
        'coveredInstrumentCount': 2,
        'deepHistoryInstrumentCount': 2,
        'currentDeepHistoryInstrumentCount': 1,
        'minimumHistoryDays': 365,
        'maximumSourceGapDays': 7,
        'sourceContinuityRequired': true,
        'pointInTimeCutoffApplied': true,
        'productionCoverageClaimed': false,
        'asOf': '2026-10-23T00:00:00+00:00',
      },
    };

Map<String, dynamic> _gaps({int total = 2, int offset = 0}) => {
      'status': 'diagnostic_only',
      'asOf': '2026-10-23T00:00:00+00:00',
      'pointInTimeCutoffApplied': true,
      'productionEvidenceClaimed': false,
      'totalBlockingCount': total,
      'blockingByReason': {
        'no_observations': total,
        'insufficient_span': 0,
        'discontinuous_source': 0,
        'stale_source': 0,
      },
      'minimumHistoryDays': 365,
      'maximumSourceGapDays': 7,
      'limit': 10,
      'offset': offset,
      'items': List.generate(
        offset >= total ? 0 : (total - offset > 10 ? 10 : total - offset),
        (index) => {
          'instrumentId': offset + index + 1,
          'symbol': 'SYM${offset + index}',
          'reason': 'no_observations',
          'sourceCount': 0,
          'bestSourceProvider': null,
          'bestHistorySpanDays': null,
          'bestMaximumGapDays': null,
        },
      ),
    };

Future<void> _mount(WidgetTester tester, AthenaReadinessService service) async {
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: SizedBox(
          height: 112,
          width: 700,
          child: SystemReadinessPanel(service: service),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  final cutoff = DateTime.parse('2026-10-23T00:00:00+00:00');

  test('PIT gap parser rejects production claims and mismatched snapshots', () {
    final valid = MarketHistoryGapsPage.fromMap(
      _gaps(), expectedAsOf: cutoff,
    );
    expect(valid.totalBlockingCount, 2);
    expect(valid.items.first.reasonLabel, 'Sin observaciones PIT');

    final future = _gaps();
    future['asOf'] = '2026-10-24T00:00:00+00:00';
    expect(
      () => MarketHistoryGapsPage.fromMap(future, expectedAsOf: cutoff),
      throwsFormatException,
    );

    final production = _gaps();
    production['productionEvidenceClaimed'] = true;
    expect(
      () => MarketHistoryGapsPage.fromMap(production, expectedAsOf: cutoff),
      throwsFormatException,
    );

    final wrongCount = _gaps();
    wrongCount['totalBlockingCount'] = 3;
    expect(
      () => MarketHistoryGapsPage.fromMap(wrongCount, expectedAsOf: cutoff),
      throwsFormatException,
    );

    final invalid = _gaps();
    (invalid['items'] as List).first['reason'] = 'ready_for_trading';
    expect(
      () => MarketHistoryGapsPage.fromMap(invalid, expectedAsOf: cutoff),
      throwsFormatException,
    );
  });

  testWidgets('Dashboard opens real PIT blockers and paginates read-only',
      (tester) async {
    final offsets = <String>[];
    final service = AthenaReadinessService(
      baseUrl: 'https://athena.example',
      client: MockClient((request) async {
        if (request.url.path == '/api/v1/readiness') {
          return http.Response(jsonEncode(_readiness()), 200);
        }
        expect(request.url.path, '/api/v1/readiness/market-history/gaps');
        expect(
          DateTime.parse(request.url.queryParameters['asOf']!)
              .isAtSameMomentAs(cutoff),
          isTrue,
        );
        expect(request.url.queryParameters['limit'], '10');
        final offset = request.url.queryParameters['offset']!;
        offsets.add(offset);
        return http.Response(
          jsonEncode(_gaps(total: 11, offset: int.parse(offset))), 200,
        );
      }),
    );
    addTearDown(service.dispose);
    await _mount(tester, service);
    await tester.tap(find.byTooltip('Ver bloqueos históricos'));
    await tester.pumpAndSettle();
    expect(find.text('Bloqueos del histórico PIT'), findsOneWidget);
    expect(find.textContaining('Bloqueados: 11'), findsOneWidget);
    expect(find.textContaining('no acredita cobertura productiva'), findsOneWidget);
    expect(offsets, ['0']);

    await tester.tap(find.text('Siguiente'));
    await tester.pumpAndSettle();
    expect(offsets, ['0', '10']);
    expect(find.text('SYM10'), findsOneWidget);
    expect(find.textContaining('Sin observaciones PIT'), findsOneWidget);
  });

  testWidgets('503 hides gap details until explicit retry succeeds',
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
        return http.Response(jsonEncode(_gaps()), 200);
      }),
    );
    addTearDown(service.dispose);
    await _mount(tester, service);
    await tester.tap(find.byTooltip('Ver bloqueos históricos'));
    await tester.pumpAndSettle();
    expect(find.text('Bloqueos PIT no disponibles.'), findsOneWidget);
    expect(find.text('SYM0'), findsNothing);

    await tester.tap(find.text('Reintentar diagnóstico'));
    await tester.pumpAndSettle();
    expect(attempts, 2);
    expect(find.text('SYM0'), findsOneWidget);
    expect(find.text('Bloqueos PIT no disponibles.'), findsNothing);
  });
}
