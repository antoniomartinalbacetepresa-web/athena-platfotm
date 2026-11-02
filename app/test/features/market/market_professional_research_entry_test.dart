import 'dart:async';

import 'package:app/core/routing/app_routes.dart';
import 'package:app/features/market/controllers/global_market_context_controller.dart';
import 'package:app/features/market/models/global_market_context.dart';
import 'package:app/features/market/presentation/pages/market_page.dart';
import 'package:app/features/market/di/market_dependencies.dart';
import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/news/models/verified_news_feed.dart';
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

MarketQuote _quote(String symbol, {bool stale = false, bool fallback = false, bool sessionDate = true, String? source = 'yahoo', int? instrumentId}) {
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
    instrumentId: instrumentId,
    canonicalIdentityStatus: instrumentId == null ? 'unresolved' : 'matched_internal_listing',
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

  testWidgets('a traceable quote opens symbol-scoped news without issuer claims',
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
          settings: settings, builder: (_) => const SizedBox(),
        );
      },
    ));
    await tester.pump();
    await tester.enterText(find.byType(TextField), ' aapl ');
    await tester.pump();
    expect(find.byKey(const Key('market-quote-open-news')), findsNothing);
    await tester.tap(find.byKey(const Key('market-quote-request')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('market-quote-open-news')));
    await tester.tap(find.byKey(const Key('market-quote-open-news')));
    await tester.pump();
    expect(route, '${AppRoutes.news}?symbol=AAPL');
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
    expect(find.byKey(const Key('market-quote-open-news')), findsNothing);
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


  testWidgets('matched internal listing reaches professional dossier route',
      (tester) async {
    final controller = _controller();
    addTearDown(controller.dispose);
    final repository = _QuoteRepository(
      (symbol) async => _quote(symbol, instrumentId: 17),
    );
    String? route;
    await tester.pumpWidget(MaterialApp(
      home: MarketPage(controller: controller, quoteRepository: repository),
      onGenerateRoute: (settings) {
        route = settings.name;
        return MaterialPageRoute<void>(
          settings: settings, builder: (_) => const SizedBox(),
        );
      },
    ));
    await tester.pump();
    await tester.enterText(find.byType(TextField), 'AAPL');
    await tester.pump();
    await tester.tap(find.byKey(const Key('market-quote-request')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('market-quote-identity-match')), findsOneWidget);
    expect(find.byKey(const Key('market-quote-identity-boundary')), findsNothing);
    await tester.ensureVisible(find.byKey(const Key('market-quote-open-research')));
    await tester.tap(find.byKey(const Key('market-quote-open-research')));
    await tester.pump();
    expect(route, '${AppRoutes.stockResearch}?symbol=AAPL&instrumentId=17');
  });

  testWidgets('contradictory internal identity blocks research navigation',
      (tester) async {
    final controller = _controller();
    addTearDown(controller.dispose);
    final repository = _QuoteRepository((symbol) async => MarketQuote(
      symbol: symbol, companyName: symbol, currentPrice: 123,
      change: 0, changePercentage: 0, updatedAt: DateTime.now().toUtc(),
      retrievedAt: DateTime.now().toUtc(), sourceProvider: 'yahoo',
      exchange: 'NMS', currency: 'USD',
      instrumentId: 17, canonicalIdentityStatus: 'unresolved',
    ));
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
  });

  testWidgets('validated quote displays independent symbol news and restores global view',
      (tester) async {
    final controller = _controller();
    addTearDown(controller.dispose);
    final repository = _QuoteRepository((symbol) async => _quote(symbol));
    var newsLoads = 0;
    Future<VerifiedNewsFeed> loadNews(int limit) async {
      newsLoads++;
      expect(limit, 5);
      final now = DateTime.now().toUtc();
      return VerifiedNewsFeed(
        query: '"AAPL" stock earnings',
        sourceProvider: 'google_news_rss',
        retrievedAt: now,
        items: [
          VerifiedNewsItem(
            title: 'AAPL results headline',
            publisher: 'Example News',
            publisherUrl: null,
            articleUrl: 'https://example.com/aapl',
            publishedAt: now.subtract(const Duration(hours: 1)),
            retrievedAt: now,
            sourceProvider: 'google_news_rss',
          ),
        ],
      );
    }
    await tester.pumpWidget(MaterialApp(home: MarketPage(
      controller: controller,
      quoteRepository: repository,
      newsFeedLoader: loadNews,
    )));
    await tester.pump();
    await tester.enterText(find.byType(TextField), 'AAPL');
    await tester.pump();
    expect(find.byKey(const Key('market-context-news-boundary')), findsNothing);
    expect(newsLoads, 0);
    await tester.tap(find.byKey(const Key('market-quote-request')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('market-context-news-boundary')), findsOneWidget);
    expect(find.textContaining('no identidad de emisor'), findsOneWidget);
    expect(find.text('AAPL results headline'), findsOneWidget);
    expect(newsLoads, 1);

    await tester.tap(find.byKey(const Key('market-context-news-toggle')));
    await tester.pump();
    expect(find.text('AAPL results headline'), findsNothing);
    await tester.tap(find.byKey(const Key('market-context-news-toggle')));
    await tester.pumpAndSettle();
    expect(find.text('AAPL results headline'), findsOneWidget);

    // A different symbol must never inherit the previous issuer's articles.
    await tester.enterText(find.byType(TextField), 'MSFT');
    await tester.pump();
    expect(find.byKey(const Key('market-context-news-boundary')), findsNothing);
    expect(find.text('AAPL results headline'), findsNothing);
  });

  testWidgets('failed quote cannot trigger contextual news fetch', (tester) async {
    final controller = _controller();
    addTearDown(controller.dispose);
    var newsLoads = 0;
    final repository = _QuoteRepository((_) async => _quote('MSFT'));
    await tester.pumpWidget(MaterialApp(home: MarketPage(
      controller: controller,
      quoteRepository: repository,
      newsFeedLoader: (_) {
        newsLoads++;
        return Future<VerifiedNewsFeed>.error(StateError('unexpected'));
      },
    )));
    await tester.pump();
    await tester.enterText(find.byType(TextField), 'AAPL');
    await tester.pump();
    await tester.tap(find.byKey(const Key('market-quote-request')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('market-quote-error')), findsOneWidget);
    expect(find.byKey(const Key('market-context-news-boundary')), findsNothing);
    expect(newsLoads, 0);
  });
}
