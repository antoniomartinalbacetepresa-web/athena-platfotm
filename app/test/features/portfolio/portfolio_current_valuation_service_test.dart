import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/models/fx_quote.dart';
import 'package:app/features/portfolio/models/portfolio_position.dart';
import 'package:app/features/portfolio/services/portfolio_current_valuation_service.dart';

PortfolioPosition position({
  required String symbol,
  required String currency,
  double shares = 2,
  double averagePrice = 100,
  double currentPrice = 120,
  DateTime? costBasisDate,
  String sourceProvider = 'yahoo',
  DateTime? observedAt,
  DateTime? retrievedAt,
}) {
  final observed = observedAt ?? DateTime.utc(2026, 9, 3, 0, 0);
  final retrieved =
      retrievedAt ?? observed.add(const Duration(seconds: 1));
  return PortfolioPosition(
    symbol: symbol,
    companyName: '$symbol Company',
    shares: shares,
    averagePrice: averagePrice,
    currentPrice: currentPrice,
    costBasisDate: costBasisDate,
    priceCurrency: currency,
    currentPriceUpdatedAt: observed,
    currentPriceSourceProvider: sourceProvider,
    currentPriceRetrievedAt: retrieved,
  );
}

FxQuote usdEur({
  double rate = 0.85,
  DateTime? observedAt,
  DateTime? retrievedAt,
  String sourceProvider = 'yahoo',
  String sourceSymbol = 'USDEUR=X',
}) {
  final observed = observedAt ?? DateTime.utc(2026, 9, 3, 0, 0);
  return FxQuote(
    status: 'ok',
    baseCurrency: 'USD',
    quoteCurrency: 'EUR',
    rate: rate,
    observedAt: observed,
    retrievedAt: retrievedAt ?? observed.add(const Duration(seconds: 1)),
    sourceProvider: sourceProvider,
    sourceSymbol: sourceSymbol,
    historicalPointInTimeEligible: false,
  );
}

void main() {
  test('values same-currency portfolio without FX and keeps historical P/L', () async {
    var fxCalls = 0;
    final service = PortfolioCurrentValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        fxCalls += 1;
        throw StateError('FX should not be requested');
      },
    );

    final valuation = await service.value(
      positions: [
        position(
          symbol: 'EUR1',
          currency: 'EUR',
          shares: 2,
          averagePrice: 100,
          currentPrice: 120,
        ),
      ],
    );

    expect(fxCalls, 0);
    expect(valuation.baseCurrency, 'EUR');
    expect(valuation.currentValueInBaseCurrency, 240);
    expect(valuation.historicalCostBasisInBaseCurrency, 200);
    expect(valuation.profitLossInBaseCurrency, 40);
    expect(valuation.profitLossPercentage, 20);
    expect(valuation.fxEvidence, isEmpty);
    expect(valuation.historicalFxEvidence, isEmpty);
    expect(valuation.usesFx, isFalse);
    expect(valuation.latestMarketObservedAt, DateTime.utc(2026, 9, 3, 0, 0));
    expect(
      valuation.latestMarketRetrievedAt,
      DateTime.utc(2026, 9, 3, 0, 0, 1),
    );
    expect(valuation.latestFxObservedAt, isNull);
    expect(valuation.latestFxRetrievedAt, isNull);
  });

  test('converts current USD value to EUR but blocks historical P/L without cost date', () async {
    final service = PortfolioCurrentValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        expect(baseCurrency, 'USD');
        expect(quoteCurrency, 'EUR');
        return usdEur(rate: 0.85);
      },
      loadHistoricalFxRate: ({
        required baseCurrency,
        required quoteCurrency,
        required observedOn,
      }) async {
        fail('Historical FX must not be requested without costBasisDate');
      },
    );

    final valuation = await service.value(
      positions: [
        position(
          symbol: 'MSFT',
          currency: 'USD',
          shares: 2,
          averagePrice: 100,
          currentPrice: 120,
        ),
      ],
    );

    expect(valuation.currentValueInBaseCurrency, 204);
    expect(valuation.positionsValued, 1);
    expect(valuation.fxEvidence, hasLength(1));
    expect(valuation.historicalFxEvidence, isEmpty);
    expect(valuation.usesFx, isTrue);
    expect(valuation.historicalCostBasisInBaseCurrency, isNull);
    expect(valuation.profitLossInBaseCurrency, isNull);
    expect(valuation.profitLossPercentage, isNull);
  });

  test('converts historical cost basis using FX from explicit economic date', () async {
    final costDate = DateTime.utc(2026, 8, 15);
    final service = PortfolioCurrentValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        return usdEur(rate: 0.85);
      },
      loadHistoricalFxRate: ({
        required baseCurrency,
        required quoteCurrency,
        required observedOn,
      }) async {
        expect(baseCurrency, 'USD');
        expect(quoteCurrency, 'EUR');
        expect(observedOn, costDate);
        return usdEur(
          rate: 0.80,
          observedAt: costDate,
          retrievedAt: DateTime.utc(2026, 9, 4),
        );
      },
    );

    final valuation = await service.value(
      positions: [
        position(
          symbol: 'MSFT',
          currency: 'USD',
          shares: 2,
          averagePrice: 100,
          currentPrice: 120,
          costBasisDate: costDate,
        ),
      ],
    );

    expect(valuation.currentValueInBaseCurrency, 204);
    expect(valuation.historicalCostBasisInBaseCurrency, 160);
    expect(valuation.profitLossInBaseCurrency, 44);
    expect(valuation.profitLossPercentage, closeTo(27.5, 1e-9));
    expect(valuation.fxEvidence, hasLength(1));
    expect(valuation.historicalFxEvidence, hasLength(1));
  });

  test('blocks historical aggregate when historical FX date is unverifiable', () async {
    final costDate = DateTime.utc(2026, 8, 15);
    final service = PortfolioCurrentValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        return usdEur(rate: 0.85);
      },
      loadHistoricalFxRate: ({
        required baseCurrency,
        required quoteCurrency,
        required observedOn,
      }) async {
        return usdEur(
          rate: 0.80,
          observedAt: DateTime.utc(2026, 8, 16),
          retrievedAt: DateTime.utc(2026, 9, 4),
        );
      },
    );

    final valuation = await service.value(
      positions: [
        position(
          symbol: 'MSFT',
          currency: 'USD',
          costBasisDate: costDate,
        ),
      ],
    );

    expect(valuation.currentValueInBaseCurrency, 204);
    expect(valuation.historicalCostBasisInBaseCurrency, isNull);
    expect(valuation.profitLossInBaseCurrency, isNull);
  });

  test('reuses one current FX quote for positions sharing the same currency', () async {
    var fxCalls = 0;
    final service = PortfolioCurrentValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        fxCalls += 1;
        return usdEur(rate: 0.5);
      },
    );

    final valuation = await service.value(
      positions: [
        position(symbol: 'A', currency: 'USD', shares: 1, currentPrice: 100),
        position(symbol: 'B', currency: 'USD', shares: 1, currentPrice: 50),
      ],
    );

    expect(fxCalls, 1);
    expect(valuation.currentValueInBaseCurrency, 75);
    expect(valuation.fxEvidence, hasLength(1));
    expect(valuation.hasHistoricalCostBasis, isFalse);
  });

  test('fails closed when a position has no verifiable currency', () async {
    final service = PortfolioCurrentValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        return usdEur();
      },
    );

    final observedAt = DateTime.utc(2026, 9, 3, 0, 0);
    final invalid = PortfolioPosition(
      symbol: 'LEGACY',
      companyName: 'Legacy',
      shares: 1,
      averagePrice: 100,
      currentPrice: 120,
      priceCurrency: null,
      currentPriceUpdatedAt: observedAt,
      currentPriceSourceProvider: 'yahoo',
      currentPriceRetrievedAt: observedAt.add(const Duration(seconds: 1)),
    );

    expect(
      () => service.value(positions: [invalid]),
      throwsStateError,
    );
  });

  test('fails closed when current market provenance is incomplete', () async {
    final service = PortfolioCurrentValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        return usdEur();
      },
    );

    final invalid = PortfolioPosition(
      symbol: 'MSFT',
      companyName: 'Microsoft',
      shares: 1,
      averagePrice: 100,
      currentPrice: 120,
      priceCurrency: 'USD',
      currentPriceUpdatedAt: DateTime.utc(2026, 9, 3, 0, 0),
      currentPriceSourceProvider: null,
      currentPriceRetrievedAt: DateTime.utc(2026, 9, 3, 0, 0, 1),
    );

    expect(
      () => service.value(positions: [invalid]),
      throwsStateError,
    );
  });

  test('fails closed when market retrieval precedes observation', () async {
    final service = PortfolioCurrentValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        return usdEur();
      },
    );

    final observedAt = DateTime.utc(2026, 9, 3, 0, 0, 2);
    final invalid = position(
      symbol: 'MSFT',
      currency: 'USD',
      observedAt: observedAt,
      retrievedAt: observedAt.subtract(const Duration(seconds: 1)),
    );

    expect(
      () => service.value(positions: [invalid]),
      throwsStateError,
    );
  });

  test('rejects FX evidence for a different currency pair', () async {
    final observedAt = DateTime.utc(2026, 9, 3, 0, 0);
    final wrongPair = FxQuote(
      status: 'ok',
      baseCurrency: 'GBP',
      quoteCurrency: 'EUR',
      rate: 1.1,
      observedAt: observedAt,
      retrievedAt: observedAt.add(const Duration(seconds: 1)),
      sourceProvider: 'yahoo',
      sourceSymbol: 'GBPEUR=X',
      historicalPointInTimeEligible: false,
    );
    final service = PortfolioCurrentValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        return wrongPair;
      },
    );

    expect(
      () => service.value(
        positions: [position(symbol: 'MSFT', currency: 'USD')],
      ),
      throwsStateError,
    );
  });

  test('rejects FX evidence without a source symbol', () async {
    final service = PortfolioCurrentValuationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        return usdEur(sourceSymbol: '');
      },
    );

    expect(
      () => service.value(
        positions: [position(symbol: 'MSFT', currency: 'USD')],
      ),
      throwsA(anything),
    );
  });
}
