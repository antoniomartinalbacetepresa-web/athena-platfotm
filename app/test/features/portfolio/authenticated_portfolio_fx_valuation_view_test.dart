import 'package:app/features/market/models/fx_quote.dart';
import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/repositories/market_repository.dart';
import 'package:app/features/portfolio/models/authenticated_portfolio_position.dart';
import 'package:app/features/portfolio/presentation/controllers/authenticated_portfolio_controller.dart';
import 'package:app/features/portfolio/presentation/controllers/authenticated_portfolio_fx_valuation_controller.dart';
import 'package:app/features/portfolio/presentation/widgets/authenticated_portfolio_view.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_fx_valuation_service.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class _ValuedPortfolioService extends AuthenticatedPortfolioService {
  _ValuedPortfolioService(this.valued);

  final List<AuthenticatedPortfolioValuedPosition> valued;

  @override
  Future<List<AuthenticatedPortfolioValuedPosition>> loadValuedPositions({
    required MarketRepository marketRepository,
  }) async => List.unmodifiable(valued);
}

class _UnusedMarketRepository implements MarketRepository {
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  final observed = DateTime.parse('2026-09-16T00:00:00Z');
  final retrieved = DateTime.parse('2026-09-16T00:01:00Z');

  AuthenticatedPortfolioValuedPosition valued({
    required int id,
    required String symbol,
    required String currency,
    required double currentValue,
  }) => AuthenticatedPortfolioValuedPosition(
        holding: AuthenticatedPortfolioPosition(
          id: id,
          symbol: symbol,
          exchange: 'NASDAQ',
          quantity: 1,
          createdAt: observed,
          updatedAt: observed,
        ),
        quote: MarketQuote(
          symbol: symbol,
          companyName: symbol,
          currentPrice: currentValue,
          change: 0,
          changePercentage: 0,
          currency: currency,
          exchange: 'NASDAQ',
          updatedAt: observed,
          sourceProvider: 'verified-market',
          retrievedAt: retrieved,
        ),
      );

  Future<AuthenticatedPortfolioController> holdings(
    List<AuthenticatedPortfolioValuedPosition> positions,
  ) async {
    final controller = AuthenticatedPortfolioController(
      portfolioService: _ValuedPortfolioService(positions),
      marketRepository: _UnusedMarketRepository(),
    );
    await controller.load();
    expect(controller.error, isNull);
    expect(controller.sessionRejected, isFalse);
    return controller;
  }

  Widget app({
    required AuthenticatedPortfolioController controller,
    AuthenticatedPortfolioFxValuationController? fx,
    String? verifiedBaseCurrency,
  }) => MaterialApp(
        home: Scaffold(
          body: AuthenticatedPortfolioView(
            controller: controller,
            fxValuationController: fx,
            verifiedBaseCurrency: verifiedBaseCurrency,
            onRetry: () {},
            onAdd: () {},
            onRemove: (_) {},
          ),
        ),
      );

  testWidgets('mixed currencies never display an unverified summed total', (tester) async {
    final controller = await holdings([
      valued(id: 1, symbol: 'AAA', currency: 'USD', currentValue: 100),
      valued(id: 2, symbol: 'BBB', currency: 'EUR', currentValue: 50),
    ]);

    await tester.pumpWidget(app(controller: controller));

    expect(find.textContaining('150.00'), findsNothing);
    expect(
      find.textContaining('Valor total no disponible: las posiciones usan monedas distintas'),
      findsOneWidget,
    );
  });

  testWidgets('verified Profile currency requires FX instead of substituting holdings currency', (tester) async {
    final controller = await holdings([
      valued(id: 1, symbol: 'AAA', currency: 'USD', currentValue: 100),
    ]);

    await tester.pumpWidget(
      app(controller: controller, verifiedBaseCurrency: 'EUR'),
    );

    expect(find.text('Valor actual: 100.00 USD'), findsNothing);
    expect(
      find.text('Valor total no disponible: se requiere FX verificado para convertir USD a EUR.'),
      findsOneWidget,
    );
    expect(find.text('Capital invertido: No disponible'), findsOneWidget);
    expect(find.textContaining('AAA (AAA)'), findsOneWidget);
    expect(find.textContaining('1.0 acciones · 100.00 USD'), findsOneWidget);
  });

  testWidgets('verified FX provenance reaches the authenticated Portfolio widget', (tester) async {
    final controller = await holdings([
      valued(id: 1, symbol: 'AAA', currency: 'USD', currentValue: 100),
      valued(id: 2, symbol: 'BBB', currency: 'EUR', currentValue: 50),
    ]);
    final fx = AuthenticatedPortfolioFxValuationController(
      valuationService: AuthenticatedPortfolioFxValuationService(
        loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async => FxQuote(
          baseCurrency: baseCurrency,
          quoteCurrency: quoteCurrency,
          rate: 0.9,
          status: 'ok',
          sourceProvider: 'verified-fx',
          sourceSymbol: '${baseCurrency.toUpperCase()}${quoteCurrency.toUpperCase()}=X',
          observedAt: observed,
          retrievedAt: retrieved,
          historicalPointInTimeEligible: false,
        ),
      ),
    );
    await fx.load(positions: controller.positions, baseCurrency: 'EUR');

    await tester.pumpWidget(
      app(controller: controller, fx: fx, verifiedBaseCurrency: 'EUR'),
    );

    expect(find.text('Valor actual: 140.00 EUR'), findsOneWidget);
    expect(find.textContaining('FX verificado: USD/EUR · verified-fx'), findsOneWidget);
    expect(find.text('Capital invertido: No disponible'), findsOneWidget);
    expect(fx.valuation!.latestFxObservedAt, observed);
    expect(fx.valuation!.latestFxRetrievedAt, retrieved);
  });

  testWidgets('failed FX reload removes the previously rendered monetary result', (tester) async {
    final controller = await holdings([
      valued(id: 1, symbol: 'AAA', currency: 'USD', currentValue: 100),
    ]);
    var fail = false;
    final fx = AuthenticatedPortfolioFxValuationController(
      valuationService: AuthenticatedPortfolioFxValuationService(
        loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
          if (fail) throw StateError('source unavailable');
          return FxQuote(
            baseCurrency: baseCurrency,
            quoteCurrency: quoteCurrency,
            rate: 0.9,
            status: 'ok',
            sourceProvider: 'verified-fx',
            sourceSymbol: '${baseCurrency.toUpperCase()}${quoteCurrency.toUpperCase()}=X',
            observedAt: observed,
            retrievedAt: retrieved,
            historicalPointInTimeEligible: false,
          );
        },
      ),
    );
    await fx.load(positions: controller.positions, baseCurrency: 'EUR');
    await tester.pumpWidget(
      app(controller: controller, fx: fx, verifiedBaseCurrency: 'EUR'),
    );
    expect(find.text('Valor actual: 90.00 EUR'), findsOneWidget);

    fail = true;
    await fx.load(positions: controller.positions, baseCurrency: 'EUR');
    await tester.pump();

    expect(find.text('Valor actual: 90.00 EUR'), findsNothing);
    expect(find.textContaining('Valor total no disponible:'), findsOneWidget);
    expect(fx.valuation, isNull);
  });
}
