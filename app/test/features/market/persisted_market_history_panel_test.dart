import 'dart:async';
import 'dart:convert';

import 'package:app/features/market/data/models/market_data_point.dart';
import 'package:app/features/market/data/models/persisted_market_history.dart';
import 'package:app/features/market/data/providers/athena_backend_market_data_provider.dart';
import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/presentation/widgets/persisted_market_history_panel.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

MarketQuote quote({String symbol = 'SYNTH', int id = 7}) => MarketQuote(
  symbol: symbol, instrumentId: id, companyName: 'Synthetic fixture',
  canonicalIdentityStatus: 'matched_internal_listing',
  currentPrice: 101, change: 0, changePercentage: 0,
  currency: 'USD', sourceProvider: 'synthetic_fixture',
  updatedAt: DateTime.now().toUtc(),
);

PersistedMarketHistory history(MarketQuote selection, DateTime asOf, {
  bool empty = false, bool truncated = false, String currency = 'USD',
}) => PersistedMarketHistory(
  asOf: asOf, truncated: truncated,
  points: empty ? [] : [MarketDataPoint(
    symbol: selection.symbol, instrumentId: selection.instrumentId,
    canonicalIdentityStatus: 'matched_internal_listing',
    timestamp: asOf.subtract(const Duration(days: 2)),
    retrievedAt: asOf.subtract(const Duration(days: 1)),
    availableAt: asOf.subtract(const Duration(days: 1)), observationId: 17,
    close: 101, volume: 200, currency: currency,
    providerId: 'athena_backend', sourceProvider: 'synthetic_fixture',
    historicalPointInTimeEligible: false, realTimePriceVerified: false,
  )],
);

Widget surface(MarketQuote selection, PersistedHistoryLoader loader) => MaterialApp(
  home: Scaffold(body: SingleChildScrollView(child: PersistedMarketHistoryPanel(
    quote: selection, loadHistory: loader,
  ))),
);

void main() {
  testWidgets('panel consumes real transport schema and exposes provenance without authority', (tester) async {
    var calls = 0;
    final provider = AthenaBackendMarketDataProvider(
      baseUrl: 'https://api.athena.test',
      client: MockClient((request) async {
        calls++;
        expect(request.url.path, '/api/v1/market/history/persisted');
        final query = request.url.queryParameters;
        expect(query['instrumentId'], '7');
        expect(query['sourceProvider'], 'synthetic_fixture');
        final cutoff = DateTime.parse(query['asOf']!);
        final retrieved = cutoff.subtract(const Duration(days: 1)).toIso8601String();
        return http.Response(jsonEncode({
          'data': [{
            'symbol': 'SYNTH', 'instrumentId': 7, 'observationId': 17,
            'canonicalIdentityStatus': 'matched_internal_listing',
            'timestamp': cutoff.subtract(const Duration(days: 2)).toIso8601String(),
            'retrievedAt': retrieved, 'availableAt': retrieved,
            'sourceProvider': 'synthetic_fixture', 'currency': 'USD',
            'close': 101, 'volume': 200,
            'historicalPointInTimeEligible': false, 'realTimePriceVerified': false,
          }],
          'provenance': {
            'retrievalMode': 'persisted_local_history', 'instrumentId': 7,
            'sourceProvider': 'synthetic_fixture', 'asOf': query['asOf'],
            'observedFrom': query['observedFrom'], 'observedTo': query['observedTo'],
            'licenceVerified': false, 'historicalPointInTimeEligible': false,
            'productionCoverageClaimed': false, 'orderExecutionAllowed': false,
            'researchOnly': true, 'truncated': true,
          },
        }), 200);
      }),
    );
    addTearDown(provider.dispose);
    await tester.pumpWidget(surface(quote(), (selection, cutoff) => provider.getPersistedHistoricalData(
      instrumentId: selection.instrumentId!, symbol: selection.symbol,
      sourceProvider: selection.sourceProvider!,
      observedFrom: cutoff.subtract(const Duration(days: 365)),
      observedTo: cutoff, asOf: cutoff,
    )));
    expect(calls, 0);
    await tester.tap(find.byKey(const Key('persisted-history-load')));
    await tester.pumpAndSettle();
    expect(calls, 1);
    expect(find.byKey(const Key('persisted-history-row-17')), findsOneWidget);
    expect(find.textContaining('cierre 101.00 USD'), findsOneWidget);
    expect(find.textContaining('volumen 200'), findsOneWidget);
    expect(find.byKey(const Key('persisted-history-truncated')), findsOneWidget);
    expect(find.textContaining('no acredita sesiones completas'), findsOneWidget);
    expect(find.byKey(const Key('persisted-history-boundary')), findsOneWidget);
  });

  testWidgets('refresh clears old prices and failure is sanitized; retry can be empty', (tester) async {
    var calls = 0;
    final failed = Completer<PersistedMarketHistory>();
    await tester.pumpWidget(surface(quote(), (selection, cutoff) {
      calls++;
      if (calls == 2) return failed.future;
      return Future.value(history(selection, cutoff, empty: calls == 3));
    }));
    await tester.tap(find.byKey(const Key('persisted-history-load')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('persisted-history-row-17')), findsOneWidget);
    await tester.tap(find.byKey(const Key('persisted-history-load')));
    await tester.pump();
    expect(find.byKey(const Key('persisted-history-row-17')), findsNothing);
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    failed.completeError(StateError('synthetic-private-token'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('persisted-history-error')), findsOneWidget);
    expect(find.textContaining('synthetic-private-token'), findsNothing);
    await tester.tap(find.byKey(const Key('persisted-history-load')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('persisted-history-empty')), findsOneWidget);
    expect(find.byKey(const Key('persisted-history-error')), findsNothing);
  });

  testWidgets('changing listing invalidates pending response without retaining prices', (tester) async {
    final pending = Completer<PersistedMarketHistory>();
    DateTime? requested;
    PersistedHistoryLoader loader = (selection, cutoff) {
      requested = cutoff;
      return pending.future;
    };
    final first = quote();
    await tester.pumpWidget(surface(first, loader));
    await tester.tap(find.byKey(const Key('persisted-history-load')));
    await tester.pump();
    await tester.pumpWidget(surface(quote(symbol: 'OTHER', id: 8), loader));
    pending.complete(history(first, requested!));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('persisted-history-row-17')), findsNothing);
    expect(find.text('Histórico guardado de OTHER'), findsOneWidget);
  });

  testWidgets('wrong currency cannot be displayed as the selected listing price', (tester) async {
    await tester.pumpWidget(surface(quote(), (selection, cutoff) async =>
      history(selection, cutoff, currency: 'EUR'))));
    await tester.tap(find.byKey(const Key('persisted-history-load')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('persisted-history-error')), findsOneWidget);
    expect(find.byKey(const Key('persisted-history-row-17')), findsNothing);
  });
}
