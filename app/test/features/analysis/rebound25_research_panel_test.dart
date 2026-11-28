import 'dart:async';
import 'dart:convert';

import 'package:app/features/analysis/presentation/widgets/rebound25_research_panel.dart';
import 'package:app/features/analysis/services/rebound25_research_service.dart';
import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../fixtures/rebound25_response_fixture.dart';

class _Service extends Rebound25ResearchService {
  final requests = <Map<String, dynamic>>[];
  Future<Rebound25ResearchResult> Function()? respond;
  @override
  Future<Rebound25ResearchResult> run(Map<String, dynamic> request) {
    requests.add(request);
    return respond!();
  }
}

Rebound25ResearchResult _result() {
  final response = jsonDecode(rebound25ResponseFixture) as Map<String, dynamic>;
  return Rebound25ResearchResult.fromJson(
    response['data'] is Map<String, dynamic>
        ? response['data'] as Map<String, dynamic>
        : response,
    request: jsonDecode(rebound25RequestFixture) as Map<String, dynamic>,
  );
}

void _owner(int id) {
  final now = DateTime.now().toUtc();
  AuthSession.instance.establish(
    accessToken: 'synthetic-$id',
    account: AuthAccount(
      id: id,
      email: '$id@example.invalid',
      isActive: true,
      createdAt: now,
      updatedAt: now,
    ),
  );
}

Widget _surface(_Service service) => MaterialApp(
  home: Scaffold(
    body: SingleChildScrollView(
      child: Rebound25ResearchPanel(service: service),
    ),
  ),
);
Future<void> _run(WidgetTester tester) async {
  await tester.ensureVisible(find.byKey(const Key('rebound25-run')));
  await tester.tap(find.byKey(const Key('rebound25-run')));
  await tester.pump();
}

void main() {
  testWidgets('replacing the service discards its pending result', (
    tester,
  ) async {
    _owner(1);
    final first = _Service(), second = _Service();
    final pending = Completer<Rebound25ResearchResult>();
    first.respond = () => pending.future;
    await tester.pumpWidget(_surface(first));
    await _run(tester);
    await tester.pumpWidget(_surface(second));
    pending.complete(_result());
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('rebound25-result')), findsNothing);
    expect(second.requests, isEmpty);
    first.dispose();
    second.dispose();
  });
  setUp(() => AuthSession.instance.clear());
  tearDown(() => AuthSession.instance.clear());
  testWidgets('guest sees synthetic boundary and cannot run', (tester) async {
    final service = _Service();
    await tester.pumpWidget(_surface(service));
    expect(
      find.byKey(const Key('rebound25-synthetic-warning')),
      findsOneWidget,
    );
    expect(find.byKey(const Key('rebound25-auth-required')), findsOneWidget);
    expect(find.byKey(const Key('rebound25-run')), findsNothing);
    expect(service.requests, isEmpty);
    service.dispose();
  });
  testWidgets('invalid parameters fail before network', (tester) async {
    _owner(1);
    final service = _Service();
    await tester.pumpWidget(_surface(service));
    expect(service.requests, isEmpty);
    await tester.enterText(find.byKey(const Key('rebound25-stop')), 'NaN');
    await _run(tester);
    expect(find.byKey(const Key('rebound25-error')), findsOneWidget);
    expect(service.requests, isEmpty);
    service.dispose();
  });
  testWidgets(
    'explicit simulation freezes the fixture and blocks double submits',
    (tester) async {
      _owner(1);
      final service = _Service();
      final pending = Completer<Rebound25ResearchResult>();
      service.respond = () => pending.future;
      await tester.pumpWidget(_surface(service));
      await _run(tester);
      await _run(tester);
      expect(service.requests.length, 1);
      final request = service.requests.single;
      expect(request['evidenceKind'], 'synthetic_fixture');
      expect((request['bars'] as List).length, 40);
      expect((request['parameters'] as Map)['lookbackSessions'], 25);
      expect((request['parameters'] as Map)['commissionBps'], 1);
      expect(find.byKey(const Key('rebound25-loading')), findsOneWidget);
      pending.complete(_result());
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('rebound25-result')), findsOneWidget);
      expect(find.textContaining('liquidación hipotética'), findsOneWidget);
      service.dispose();
    },
  );
  testWidgets(
    'retry retains the same request and reset permits new parameters',
    (tester) async {
      _owner(1);
      final service = _Service();
      service.respond = () async => throw StateError('Synthetic interruption');
      await tester.pumpWidget(_surface(service));
      await _run(tester);
      await tester.pumpAndSettle();
      await _run(tester);
      await tester.pumpAndSettle();
      expect(service.requests.length, 2);
      expect(identical(service.requests[0], service.requests[1]), true);
      await tester.ensureVisible(find.text('NUEVOS PARÁMETROS'));
      await tester.tap(find.text('NUEVOS PARÁMETROS'));
      await tester.pump();
      await tester.enterText(find.byKey(const Key('rebound25-target')), '3');
      await _run(tester);
      await tester.pumpAndSettle();
      expect((service.requests.last['parameters'] as Map)['takeProfitPct'], 3);
      expect(identical(service.requests.first, service.requests.last), false);
      service.dispose();
    },
  );
  testWidgets(
    'owner switch hides late simulation results and resets parameter context',
    (tester) async {
      _owner(1);
      final service = _Service();
      final pending = Completer<Rebound25ResearchResult>();
      service.respond = () => pending.future;
      await tester.pumpWidget(_surface(service));
      await tester.enterText(find.byKey(const Key('rebound25-target')), '7');
      await _run(tester);
      _owner(2);
      await tester.pump();
      pending.complete(_result());
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('rebound25-result')), findsNothing);
      expect(
        tester
            .widget<TextField>(find.byKey(const Key('rebound25-target')))
            .controller!
            .text,
        '2',
      );
      service.dispose();
    },
  );
}
