import 'dart:async';

import 'package:app/core/routing/app_routes.dart';
import 'package:app/features/market/controllers/global_market_context_controller.dart';
import 'package:app/features/market/models/global_market_context.dart';
import 'package:app/features/market/presentation/pages/market_page.dart';
import 'package:app/features/market/di/market_dependencies.dart';
import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/repositories/market_repository.dart';
import 'package:app/features/market/services/global_market_data_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class _IdleMarketService extends GlobalMarketDataService {
  _IdleMarketService(MarketDependencies dependencies)
      : super(
          regionalMarketContextService:
              dependencies.globalMarketDataService.regionalMarketContextService,
          globalMarketContextService:
              dependencies.globalMarketDataService.globalMarketContextService,
          marketUniverseRepository:
              dependencies.globalMarketDataService.marketUniverseRepository,
          regionalMarketWeightService:
              dependencies.globalMarketDataService.regionalMarketWeightService,
          marketUniverseStatusProvider:
              dependencies.globalMarketDataService.marketUniverseStatusProvider,
        );

  @override
  Future<GlobalMarketContext> getGlobalContext() =>
      Future<GlobalMarketContext>.error(StateError('test market unavailable'));
}

GlobalMarketContextController _controller() {
  final dependencies = MarketDependencies.create();
  return GlobalMarketContextController(
    service: _IdleMarketService(dependencies),
  );
}


class _QuoteRepository implements MarketRepository {
  final Future<MarketQuote> Function(String) fetch;
  final requested = <String>[];
  _QuoteRepository(this.fetch);
  @override
  Future<MarketQuote> getQuote(String symbol) {
    requested.add(symbol);
    return fetch(symbol);
  }
}

MarketQuote _quote(String symbol, {bool stale = false, bool fallback = false, bool sessionDate = true, String? source = 'yahoo'}) {
  final now = DateTime.now().toUtc();
  return MarketQuote(
    symbol: symbol, companyName: symbol, currentPrice: 123.45,
    change: 1, changePercentage: 0.82, currency: 'USD', exchange: 'NMS',
    updatedAt: now.subtract(Duration(hours: stale ? 72 : 1)),
    retrievedAt: now.subtract(const Duration(minutes: 1)),
    sourceProvider: source,
    quoteMode: fallback ? 'historical_daily_close_fallback' : 'provider_fast_info',
    priceSessionDate: fallback && sessionDate ? '2026-10-30' : null,
    realTimePriceVerified: false,
    historicalPointInTimeEligible: false,
  );
}

void main() {
  testWidgets('Market keeps professional research closed until a symbol exists',
      (tester) async {
    final controller = _controller();
    addTearDown(controller.dispose);
    await tester.pumpWidget(MaterialApp(home: MarketPage(controller: controller)));
    await tester.pump();

    final button = find.byKey(const Key('market-open-professional-research'));
    expect(button, findsOneWidget);
    expect(tester.widget<FilledButton>(button).onPressed, isNull);

    await tester.enterText(find.byType(TextField), ' aapl ');
    await tester.pump();
    expect(tester.widget<FilledButton>(button).onPressed, isNotNull);
  });

  testWidgets('Market normalizes symbol before opening professional research',
      (tester) async {
    final controller = _controller();
    addTearDown(controller.dispose);
    String? route;
    await tester.pumpWidget(
      MaterialApp(
        home: MarketPage(controller: controller),
        onGenerateRoute: (settings) {
          route = settings.name;
          return MaterialPageRoute<void>(
            settings: settings,
            builder: (_) => const SizedBox(),
          );
        },
      ),
    );
    await tester.pump();

    await tester.enterText(find.byType(TextField), ' aapl ');
    await tester.pump();
    await tester.tap(find.byKey(const Key('market-open-professional-research')));
    await tester.pump();

    expect(route, '${AppRoutes.stockResearch}?symbol=AAPL');
  });
  testWidgets('Market displays a selected company quote with declared provenance',
      (tester) async {
    final controller = _controller();
    addTearDown(controller.dispose);
    final repository = _QuoteRepository((symbol) async => _quote(symbol));
    await tester.pumpWidget(MaterialApp(home: MarketPage(
      controller: controller, quoteRepository: repository,
    )));
    await tester.pump();
    await tester.enterText(find.byType(TextField), ' aapl ');
    await tester.pump();
    await tester.tap(find.byKey(const Key('market-quote-request')));
    await tester.pumpAndSettle();
    expect(repository.requested, ['AAPL']);
    expect(find.textContaining('AAPL · 123.45 USD'), findsOneWidget);
    expect(find.textContaining('Fuente declarada: yahoo'), findsOneWidget);
    expect(find.byKey(const Key('market-quote-timestamps')), findsOneWidget);
  });

  testWidgets('Market fails closed on a different company or missing provenance',
      (tester) async {
    final controller = _controller();
    addTearDown(controller.dispose);
    final repository = _QuoteRepository((_) async => _quote('MSFT'));
    await tester.pumpWidget(MaterialApp(home: MarketPage(
      controller: controller, quoteRepository: repository,
    )));
    await tester.pump();
    await tester.enterText(find.byType(TextField), 'AAPL');
    await tester.pump();
    await tester.tap(find.byKey(const Key('market-quote-request')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('market-quote-error')), findsOneWidget);
    expect(find.byKey(const Key('market-quote-price')), findsNothing);
  });

  testWidgets('Market never reuses an old quote after a symbol change',
      (tester) async {
    final controller = _controller();
    addTearDown(controller.dispose);
    final pending = Completer<MarketQuote>();
    final repository = _QuoteRepository(
      (symbol) => symbol == 'AAPL' ? pending.future : Future.value(_quote(symbol)),
    );
    await tester.pumpWidget(MaterialApp(home: MarketPage(
      controller: controller, quoteRepository: repository,
    )));
    await tester.pump();
    await tester.enterText(find.byType(TextField), 'AAPL');
    await tester.pump();
    await tester.tap(find.byKey(const Key('market-quote-request')));
    await tester.pump();
    await tester.enterText(find.byType(TextField), 'MSFT');
    await tester.pump();
    expect(find.byKey(const Key('market-quote-price')), findsNothing);
    await tester.tap(find.byKey(const Key('market-quote-request')));
    await tester.pumpAndSettle();
    expect(find.textContaining('MSFT · 123.45'), findsOneWidget);
    pending.complete(_quote('AAPL'));
    await tester.pump();
    expect(find.textContaining('AAPL · 123.45'), findsNothing);
  });

  testWidgets('Market marks old prices and hides provider exception details',
      (tester) async {
    final controller = _controller();
    addTearDown(controller.dispose);
    var fail = false;
    final repository = _QuoteRepository((symbol) async {
      if (fail) throw StateError('provider-secret=hidden');
      return _quote(symbol, stale: true);
    });
    await tester.pumpWidget(MaterialApp(home: MarketPage(
      controller: controller, quoteRepository: repository,
    )));
    await tester.pump();
    await tester.enterText(find.byType(TextField), 'AAPL');
    await tester.pump();
    await tester.tap(find.byKey(const Key('market-quote-request')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('market-quote-stale')), findsOneWidget);
    fail = true;
    await tester.tap(find.byKey(const Key('market-quote-request')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('market-quote-price')), findsNothing);
    expect(find.byKey(const Key('market-quote-error')), findsOneWidget);
    expect(find.textContaining('provider-secret'), findsNothing);
  });


  testWidgets('a traceable quote opens the dossier for that exact symbol',
      (tester) async {
    final controller = _controller();
    addTearDown(controller.dispose);
    final repository = _QuoteRepository((symbol) async => _quote(symbol));
    String? route;
    await tester.pumpWidget(MaterialApp(
      home: MarketPage(controller: controller, quoteRepository: repository),
      onGenerateRoute: (settings) {
        route = settings.name;
        return MaterialPageRoute<void>(
          settings: settings,
          builder: (_) => const SizedBox(),
        );
      },
    ));
    await tester.pump();
    await tester.enterText(find.byType(TextField), ' aapl ');
    await tester.pump();
    expect(find.byKey(const Key('market-quote-open-research')), findsNothing);
    await tester.tap(find.byKey(const Key('market-quote-request')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('market-quote-research-boundary')), findsOneWidget);
    expect(find.byKey(const Key('market-quote-identity-boundary')), findsOneWidget);
    await tester.ensureVisible(find.byKey(const Key('market-quote-open-research')));
    await tester.tap(find.byKey(const Key('market-quote-open-research')));
    await tester.pump();
    expect(route, '${AppRoutes.stockResearch}?symbol=AAPL');
  });

  testWidgets('a rejected quote never offers the verified research entry',
      (tester) async {
    final controller = _controller();
    addTearDown(controller.dispose);
    final repository = _QuoteRepository((_) async => _quote('MSFT'));
    await tester.pumpWidget(MaterialApp(
      home: MarketPage(controller: controller, quoteRepository: repository),
    ));
    await tester.pump();
    await tester.enterText(find.byType(TextField), 'AAPL');
    await tester.pump();
    await tester.tap(find.byKey(const Key('market-quote-request')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('market-quote-error')), findsOneWidget);
    expect(find.byKey(const Key('market-quote-open-research')), findsNothing);
    expect(find.byKey(const Key('market-quote-research-boundary')), findsNothing);
  });


  testWidgets('daily-close fallback is never presented as a live quote',
      (tester) async {
    final controller = _controller();
    addTearDown(controller.dispose);
    final repository = _QuoteRepository(
      (symbol) async => _quote(symbol, fallback: true),
    );
    await tester.pumpWidget(MaterialApp(
      home: MarketPage(controller: controller, quoteRepository: repository),
    ));
    await tester.pump();
    await tester.enterText(find.byType(TextField), 'AAPL');
    await tester.pump();
    await tester.tap(find.byKey(const Key('market-quote-request')));
    await tester.pumpAndSettle();
    expect(find.textContaining('ÚLTIMO CIERRE DIARIO DISPONIBLE'), findsOneWidget);
    expect(find.textContaining('sesión 2026-10-30'), findsOneWidget);
    expect(find.byKey(const Key('market-quote-stale')), findsOneWidget);
  });

  testWidgets('daily-close fallback without a session date fails closed',
      (tester) async {
    final controller = _controller();
    addTearDown(controller.dispose);
    final repository = _QuoteRepository(
      (symbol) async => _quote(symbol, fallback: true, sessionDate: false),
    );
    await tester.pumpWidget(MaterialApp(
      home: MarketPage(controller: controller, quoteRepository: repository),
    ));
    await tester.pump();
    await tester.enterText(find.byType(TextField), 'AAPL');
    await tester.pump();
    await tester.tap(find.byKey(const Key('market-quote-request')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('market-quote-error')), findsOneWidget);
    expect(find.byKey(const Key('market-quote-open-research')), findsNothing);
    expect(find.byKey(const Key('market-quote-price')), findsNothing);
  });

}
