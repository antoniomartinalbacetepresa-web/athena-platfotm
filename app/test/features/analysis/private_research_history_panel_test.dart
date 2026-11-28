import 'dart:async';
import 'package:app/features/auth/models/auth_account.dart';

import 'package:app/features/analysis/presentation/widgets/private_research_history_panel.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/analysis/services/private_research_history_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class _DelayedHistory extends PrivateResearchHistoryService {
  final requests = <Completer<PrivateResearchPage>>[];
  @override
  Future<PrivateResearchPage> load({required String symbol, int limit = 20}) {
    final pending = Completer<PrivateResearchPage>();
    requests.add(pending);
    return pending.future;
  }
}

void _owner(int id) {
  final now = DateTime.now().toUtc();
  AuthSession.instance.establish(accessToken: 'synthetic-$id', account: AuthAccount(
    id: id, email: '$id@example.invalid', isActive: true, createdAt: now, updatedAt: now));
}

void main() {
  testWidgets('replacing a private view before rebuilding observes stale request errors', (tester) async {
    _owner(1);
    final service = _DelayedHistory();
    await tester.pumpWidget(MaterialApp(home: Scaffold(
      body: PrivateResearchHistoryPanel(symbol: 'SYNTH', service: service))));
    _owner(2); // Schedules another load without attaching a new FutureBuilder yet.
    await tester.pumpWidget(const SizedBox.shrink());
    expect(service.requests.length, 2);
    for (final request in service.requests) {
      request.completeError(StateError('Synthetic account switch'));
    }
    await tester.pump();
    expect(tester.takeException(), isNull);
    AuthSession.instance.clear(); service.dispose();
  });
  testWidgets('anonymous professional research does not request private history', (tester) async {
    AuthSession.instance.clear();
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: PrivateResearchHistoryPanel(symbol: 'AAPL')),
    ));
    expect(find.byKey(const Key('private-research-auth-required')), findsOneWidget);
    expect(find.byKey(const Key('private-research-loading')), findsNothing);
  });

  testWidgets('anonymous injected service cannot bypass private auth boundary', (tester) async {
    AuthSession.instance.clear();
    final service = PrivateResearchHistoryService();
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: PrivateResearchHistoryPanel(symbol: 'AAPL', service: service)),
    ));
    expect(find.byKey(const Key('private-research-auth-required')), findsOneWidget);
    expect(find.byKey(const Key('private-research-loading')), findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
    service.dispose();
  });

  testWidgets('changing symbol keeps anonymous private history closed', (tester) async {
    AuthSession.instance.clear();
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: PrivateResearchHistoryPanel(symbol: 'AAPL')),
    ));
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: PrivateResearchHistoryPanel(symbol: 'MSFT')),
    ));
    expect(find.byKey(const Key('private-research-auth-required')), findsOneWidget);
    expect(find.byKey(const Key('private-research-heading')), findsNothing);
  });
}
