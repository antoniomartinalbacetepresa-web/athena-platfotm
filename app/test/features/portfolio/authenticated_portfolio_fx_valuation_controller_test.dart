import 'dart:async';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
import 'package:app/features/market/models/fx_quote.dart';
import 'package:app/features/portfolio/models/authenticated_portfolio_view_position.dart';
import 'package:app/features/portfolio/presentation/controllers/authenticated_portfolio_fx_valuation_controller.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_fx_valuation_service.dart';
import 'package:flutter_test/flutter_test.dart';

class _TokenStore implements AuthTokenStore {
  @override
  Future<void> deleteAccessToken() async {}
  @override
  Future<String?> readAccessToken() async => null;
  @override
  Future<void> writeAccessToken(String token) async {}
}

void main() {
  final observed = DateTime.parse('2026-09-16T00:00:00Z');
  final retrieved = DateTime.parse('2026-09-16T00:01:00Z');

  AuthenticatedPortfolioViewPosition position({required String currency, required double currentValue}) => AuthenticatedPortfolioViewPosition(
        serverPositionId: 1, symbol: 'AAA', companyName: 'AAA', exchange: 'NASDAQ', quantity: 1,
        currency: currency, currentPrice: currentValue, averagePurchasePrice: null, currentValue: currentValue,
        investedValue: null, profitLoss: null, profitLossPercentage: null, marketSourceProvider: 'verified-market',
        marketObservedAt: observed, marketRetrievedAt: retrieved,
      );

  FxQuote fx(double rate, {String baseCurrency = 'USD', String quoteCurrency = 'EUR'}) => FxQuote(
        baseCurrency: baseCurrency, quoteCurrency: quoteCurrency, rate: rate, status: 'ok', sourceProvider: 'verified-fx',
        sourceSymbol: baseCurrency == quoteCurrency ? null : '${baseCurrency.toUpperCase()}${quoteCurrency.toUpperCase()}=X',
        observedAt: observed, retrievedAt: retrieved, historicalPointInTimeEligible: false,
      );

  AuthAccount account(int id) => AuthAccount(
        id: id, email: 'owner$id@example.com', displayName: 'Owner $id', isActive: true,
        createdAt: observed, updatedAt: observed,
      );

  test('verified load exposes valuation and clears loading/error', () async {
    final controller = AuthenticatedPortfolioFxValuationController(
      valuationService: AuthenticatedPortfolioFxValuationService(
        loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async => fx(0.9),
      ),
    );
    await controller.load(positions: [position(currency: 'USD', currentValue: 100)], baseCurrency: 'EUR');
    expect(controller.isLoading, isFalse); expect(controller.error, isNull);
    expect(controller.hasVerifiedValuation, isTrue); expect(controller.valuation!.currentValueInBaseCurrency, 90);
    controller.dispose();
  });

  test('authoritative failure removes a previously verified valuation', () async {
    var fail = false;
    final controller = AuthenticatedPortfolioFxValuationController(
      valuationService: AuthenticatedPortfolioFxValuationService(
        loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
          if (fail) throw StateError('temporary failure'); return fx(0.9);
        },
      ),
    );
    await controller.load(positions: [position(currency: 'USD', currentValue: 100)], baseCurrency: 'EUR');
    expect(controller.hasVerifiedValuation, isTrue);
    fail = true;
    await controller.load(positions: [position(currency: 'USD', currentValue: 100)], baseCurrency: 'EUR');
    expect(controller.hasVerifiedValuation, isFalse); expect(controller.valuation, isNull); expect(controller.error, isNotNull);
    controller.dispose();
  });

  test('Profile base-currency change cannot retain valuation in the old currency', () async {
    final controller = AuthenticatedPortfolioFxValuationController(
      valuationService: AuthenticatedPortfolioFxValuationService(
        loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
          if (quoteCurrency == 'EUR') return fx(0.9, baseCurrency: baseCurrency, quoteCurrency: quoteCurrency);
          throw StateError('GBP authority unavailable');
        },
      ),
    );
    final positions = [position(currency: 'USD', currentValue: 100)];
    await controller.load(positions: positions, baseCurrency: 'EUR');
    expect(controller.hasVerifiedValuation, isTrue); expect(controller.valuation!.baseCurrency, 'EUR');
    await controller.load(positions: positions, baseCurrency: 'GBP');
    expect(controller.hasVerifiedValuation, isFalse); expect(controller.valuation, isNull); expect(controller.error, isNotNull);
    controller.dispose();
  });

  test('clear invalidates an in-flight result and removes monetary state', () async {
    final pending = Completer<FxQuote>();
    final controller = AuthenticatedPortfolioFxValuationController(
      valuationService: AuthenticatedPortfolioFxValuationService(
        loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) => pending.future,
      ),
    );
    final load = controller.load(positions: [position(currency: 'USD', currentValue: 100)], baseCurrency: 'EUR');
    expect(controller.isLoading, isTrue); controller.clear();
    expect(controller.isLoading, isFalse); expect(controller.valuation, isNull); expect(controller.error, isNull);
    pending.complete(fx(0.9)); await load;
    expect(controller.hasVerifiedValuation, isFalse); expect(controller.valuation, isNull);
    controller.dispose();
  });

  test('newer load wins when an older FX request completes later', () async {
    final first = Completer<FxQuote>(); var calls = 0;
    final controller = AuthenticatedPortfolioFxValuationController(
      valuationService: AuthenticatedPortfolioFxValuationService(
        loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) {
          calls += 1; if (calls == 1) return first.future; return Future.value(fx(0.8));
        },
      ),
    );
    final older = controller.load(positions: [position(currency: 'USD', currentValue: 100)], baseCurrency: 'EUR');
    final newer = controller.load(positions: [position(currency: 'USD', currentValue: 100)], baseCurrency: 'EUR');
    await newer; expect(controller.valuation!.currentValueInBaseCurrency, 80);
    first.complete(fx(0.9)); await older;
    expect(controller.valuation!.currentValueInBaseCurrency, 80); expect(controller.hasVerifiedValuation, isTrue);
    controller.dispose();
  });

  test('owner replacement clears completed FX valuation synchronously', () async {
    final session = AuthSession.forTesting(_TokenStore());
    session.establish(accessToken: 'owner-a', account: account(1));
    final controller = AuthenticatedPortfolioFxValuationController(
      session: session,
      valuationService: AuthenticatedPortfolioFxValuationService(
        loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async => fx(0.9),
      ),
    );
    await controller.load(positions: [position(currency: 'USD', currentValue: 100)], baseCurrency: 'EUR');
    expect(controller.hasVerifiedValuation, isTrue);
    session.establish(accessToken: 'owner-b', account: account(2));
    expect(controller.hasVerifiedValuation, isFalse);
    expect(controller.valuation, isNull);
    expect(controller.error, isNull);
    controller.dispose();
  });

  test('owner replacement invalidates in-flight FX result from old owner', () async {
    final session = AuthSession.forTesting(_TokenStore());
    session.establish(accessToken: 'owner-a', account: account(1));
    final pending = Completer<FxQuote>();
    final controller = AuthenticatedPortfolioFxValuationController(
      session: session,
      valuationService: AuthenticatedPortfolioFxValuationService(
        loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) => pending.future,
      ),
    );
    final load = controller.load(positions: [position(currency: 'USD', currentValue: 100)], baseCurrency: 'EUR');
    expect(controller.isLoading, isTrue);
    session.establish(accessToken: 'owner-b', account: account(2));
    expect(controller.isLoading, isFalse); expect(controller.valuation, isNull);
    pending.complete(fx(0.9)); await load;
    expect(controller.hasVerifiedValuation, isFalse); expect(controller.valuation, isNull); expect(controller.error, isNull);
    controller.dispose();
  });
}
