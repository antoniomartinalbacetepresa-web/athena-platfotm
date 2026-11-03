import 'package:app/features/analysis/presentation/widgets/private_research_history_panel.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/analysis/services/private_research_history_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
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
