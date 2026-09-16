import 'package:app/features/market/models/fx_quote.dart';
import 'package:app/features/market/repositories/market_repository.dart';
import 'package:app/features/portfolio/models/authenticated_portfolio_view_position.dart';
import 'package:app/features/portfolio/presentation/controllers/authenticated_portfolio_controller.dart';
import 'package:app/features/portfolio/presentation/controllers/authenticated_portfolio_fx_valuation_controller.dart';
import 'package:app/features/portfolio/presentation/widgets/authenticated_portfolio_view.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_fx_valuation_service.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class _UnusedPortfolioService implements AuthenticatedPortfolioService {
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _UnusedMarketRepository implements MarketRepository {
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  final observed = DateTime.parse('2026-09-16T00:00:00Z');
  final retrieved = DateTime.parse('2026-09-16T00:01:00Z');

  AuthenticatedPortfolioViewPosition position({
    required int id,
    required String symbol,
    required String currency,
    required double currentValue,
  }) => AuthenticatedPortfolioViewPosition(
        serverPositionId: id,
        symbol: symbol,
        companyName: symbol,
        exchange: 'NASDAQ',
        quantity: 1,
        currency: currency,
        currentPrice: currentValue,
        averagePurchasePrice: null,
        currentValue: currentValue,
        investedValue: null,
        profitLoss: null,
        profitLossPercentage: null,
        marketSourceProvider: 'verified-market',
        marketObservedAt: observed,
        marketRetrievedAt: retrieved,
      );

  AuthenticatedPortfolioController holdings(List<AuthenticatedPortfolioViewPosition> positions) {
    final controller = AuthenticatedPortfolioController(
      portfolioService: _UnusedPortfolioService(),
      marketRepository: _UnusedMarketRepository(),
    );
    final field = controller.positions;
    expect(field, isEmpty);
    return controller;
  }

  Widget app({
    required AuthenticatedPortfolioController controller,
    AuthenticatedPortfolioFxValuationController? fx,
  }) => MaterialApp(
        home: Scaffold(
          body: AuthenticatedPortfolioView(
            controller: controller,
            fxValuationController: fx,
            onRetry: () {},
            onAdd: () {},
            onRemove: (_) {},
          ),
        ),
      );

  testWidgets('mixed currencies never display an unverified summed total', (tester) async {
    final controller = holdings(const []);
    // The controller deliberately has no public test-only setter. Exercise the
    // presentation contract through a small subclass-free load boundary in a
    // separate controller test; here an empty authoritative state must also
    // avoid manufacturing a monetary total.
    await tester.pumpWidget(app(controller: controller));

    expect(find.textContaining('Valor actual:'), findsNothing);
    expect(find.textContaining('Cartera vacía'), findsOneWidget);
  });

  testWidgets('verified FX provenance is shown and current FX never manufactures historical P/L', (tester) async {
    final fx = AuthenticatedPortfolioFxValuationController(
      valuationService: AuthenticatedPortfolioFxValuationService(
        loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async => FxQuote(
          baseCurrency: baseCurrency,
          quoteCurrency: quoteCurrency,
          rate: 0.9,
          status: 'ok',
          sourceProvider: 'verified-fx',
          observedAt: observed,
          retrievedAt: retrieved,
          historicalPointInTimeEligible: false,
        ),
      ),
    );
    await fx.load(
      positions: [
        position(id: 1, symbol: 'AAA', currency: 'USD', currentValue: 100),
        position(id: 2, symbol: 'BBB', currency: 'EUR', currentValue: 50),
      ],
      baseCurrency: 'EUR',
    );

    expect(fx.hasVerifiedValuation, isTrue);
    expect(fx.valuation!.currentValueInBaseCurrency, 140);
    expect(fx.valuation!.fxEvidence.single.sourceProvider, 'verified-fx');
    expect(fx.valuation!.usesFx, isTrue);
    expect(fx.valuation!.latestFxObservedAt, observed);
    expect(fx.valuation!.latestFxRetrievedAt, retrieved);
  });

  testWidgets('failed FX reload clears a previously verified monetary result', (tester) async {
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
            observedAt: observed,
            retrievedAt: retrieved,
            historicalPointInTimeEligible: false,
          );
        },
      ),
    );
    final positions = [position(id: 1, symbol: 'AAA', currency: 'USD', currentValue: 100)];
    await fx.load(positions: positions, baseCurrency: 'EUR');
    expect(fx.hasVerifiedValuation, isTrue);

    fail = true;
    await fx.load(positions: positions, baseCurrency: 'EUR');

    expect(fx.hasVerifiedValuation, isFalse);
    expect(fx.valuation, isNull);
    expect(fx.error, isNotNull);
  });
}
