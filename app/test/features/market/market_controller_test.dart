import 'dart:async';

import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/controllers/market_controller.dart';
import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/repositories/market_repository.dart';

MarketQuote quoteFor(String symbol, {double price = 305.93}) => MarketQuote(
      symbol: symbol,
      companyName: 'Empresa verificada',
      currentPrice: price,
      change: 0.67,
      changePercentage: 0.21949,
      updatedAt: DateTime.utc(2026, 1, 1),
    );

class FakeMarketRepository implements MarketRepository {
  @override
  Future<MarketQuote> getQuote(String symbol) async => quoteFor(symbol);
}

class PendingMarketRepository implements MarketRepository {
  final Map<String, Completer<MarketQuote>> requests = {};

  @override
  Future<MarketQuote> getQuote(String symbol) =>
      requests.putIfAbsent(symbol, () => Completer<MarketQuote>()).future;
}

class WrongIdentityMarketRepository implements MarketRepository {
  @override
  Future<MarketQuote> getQuote(String symbol) async => quoteFor('MSFT');
}

class InvalidPriceMarketRepository implements MarketRepository {
  @override
  Future<MarketQuote> getQuote(String symbol) async =>
      quoteFor(symbol, price: double.nan);
}

class FailingMarketRepository implements MarketRepository {
  @override
  Future<MarketQuote> getQuote(String symbol) async =>
      throw StateError('private provider token=do-not-display');
}

void main() {
  test('MarketController carga correctamente una cotización', () async {
    final controller = MarketController(repository: FakeMarketRepository());

    await controller.loadQuote('aapl');

    expect(controller.isLoading, isFalse);
    expect(controller.error, isNull);
    expect(controller.quote, isNotNull);
    expect(controller.quote!.symbol, 'AAPL');
    expect(controller.quote!.companyName, 'Empresa verificada');
    expect(controller.quote!.currentPrice, 305.93);
    expect(controller.quote!.changePercentage, 0.21949);
    controller.dispose();
  });

  test('MarketController notifica los cambios durante la carga', () async {
    final controller = MarketController(repository: FakeMarketRepository());
    var notifications = 0;
    controller.addListener(() => notifications++);

    await controller.loadQuote('AAPL');

    expect(notifications, greaterThanOrEqualTo(2));
    expect(controller.isLoading, isFalse);
    controller.dispose();
  });

  test('newer symbol wins even when older quote completes last', () async {
    final repository = PendingMarketRepository();
    final controller = MarketController(repository: repository);
    final stale = controller.loadQuote('AAPL');
    final current = controller.loadQuote('msft');

    expect(controller.isLoading, isTrue);
    expect(controller.quote, isNull);
    repository.requests['MSFT']!.complete(quoteFor('MSFT'));
    await current;
    expect(controller.quote?.symbol, 'MSFT');
    expect(controller.error, isNull);

    repository.requests['AAPL']!.complete(quoteFor('AAPL'));
    await stale;
    expect(controller.quote?.symbol, 'MSFT');
    expect(controller.isLoading, isFalse);
    controller.dispose();
  });

  test('empty symbol revokes pending quote and clears loading state', () async {
    final repository = PendingMarketRepository();
    final controller = MarketController(repository: repository);
    final stale = controller.loadQuote('AAPL');

    await controller.loadQuote('  ');
    expect(controller.quote, isNull);
    expect(controller.isLoading, isFalse);
    expect(controller.error, contains('vacío'));

    repository.requests['AAPL']!.complete(quoteFor('AAPL'));
    await stale;
    expect(controller.quote, isNull);
    expect(controller.error, contains('vacío'));
    controller.dispose();
  });

  test('wrong-symbol provider response is rejected without showing a price',
      () async {
    final controller = MarketController(
      repository: WrongIdentityMarketRepository(),
    );
    await controller.loadQuote('AAPL');
    expect(controller.quote, isNull);
    expect(controller.isLoading, isFalse);
    expect(controller.error, isNotNull);
    controller.dispose();
  });

  test('non-finite price is rejected instead of being displayed', () async {
    final controller = MarketController(
      repository: InvalidPriceMarketRepository(),
    );
    await controller.loadQuote('AAPL');
    expect(controller.quote, isNull);
    expect(controller.error, isNotNull);
    controller.dispose();
  });

  test('provider failure never leaks private transport diagnostics', () async {
    final controller = MarketController(repository: FailingMarketRepository());
    await controller.loadQuote('AAPL');
    expect(controller.quote, isNull);
    expect(controller.error, isNot(contains('do-not-display')));
    expect(controller.error, isNotNull);
    controller.dispose();
  });

  test('clear revokes an in-flight response before another quote', () async {
    final repository = PendingMarketRepository();
    final controller = MarketController(repository: repository);
    final stale = controller.loadQuote('AAPL');
    controller.clear();
    expect(controller.isLoading, isFalse);
    expect(controller.quote, isNull);
    repository.requests['AAPL']!.complete(quoteFor('AAPL'));
    await stale;
    expect(controller.quote, isNull);
    expect(controller.error, isNull);
    controller.dispose();
  });

  test('disposed controller ignores a late quote without notifying', () async {
    final repository = PendingMarketRepository();
    final controller = MarketController(repository: repository);
    var notifications = 0;
    controller.addListener(() => notifications++);
    final pending = controller.loadQuote('AAPL');
    final beforeDispose = notifications;
    controller.dispose();
    repository.requests['AAPL']!.complete(quoteFor('AAPL'));
    await pending;
    expect(controller.quote, isNull);
    expect(notifications, beforeDispose);
  });
}
