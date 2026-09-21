import 'dart:async';

import 'package:app/features/market/controllers/global_market_context_controller.dart';
import 'package:app/features/market/models/global_market_context.dart';
import 'package:app/features/market/presentation/pages/market_page.dart';
import 'package:app/features/market/services/global_market_data_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class _ControlledMarketService implements GlobalMarketDataService {
  _ControlledMarketService(this.responses);
  final List<Future<GlobalMarketContext>> responses;
  var calls = 0;

  @override
  Future<GlobalMarketContext> getGlobalContext() => responses[calls++];
}

GlobalMarketContext _context(String summary) => GlobalMarketContext.empty().copyWith(
      summary: summary,
      updatedAt: DateTime.utc(2026, 9, 21, 3),
    );

void main() {
  testWidgets('Market page hides stale snapshot while refresh is pending', (tester) async {
    final pending = Completer<GlobalMarketContext>();
    final service = _ControlledMarketService([
      Future.value(_context('Snapshot inicial')),
      pending.future,
    ]);
    final controller = GlobalMarketContextController(service: service);

    await tester.pumpWidget(MaterialApp(home: MarketPage(controller: controller)));
    await tester.pumpAndSettle();
    expect(find.text('Snapshot inicial'), findsOneWidget);

    await tester.tap(find.byTooltip('Actualizar mercado'));
    await tester.pump();
    expect(find.text('Snapshot inicial'), findsNothing);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    pending.complete(_context('Snapshot actualizado'));
    await tester.pumpAndSettle();
    expect(find.text('Snapshot actualizado'), findsOneWidget);
    expect(find.text('Snapshot inicial'), findsNothing);
    expect(service.calls, 2);

    controller.dispose();
  });
}
