import 'package:flutter_test/flutter_test.dart';
import 'package:app/features/portfolio/models/authenticated_portfolio_view_position.dart';
import 'package:app/features/portfolio/models/portfolio_instrument_identity.dart';
import 'package:app/features/portfolio/models/portfolio_pair_correlation.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_correlation_service.dart';

void main() {
  final observed = DateTime.utc(2026, 10, 25, 12);
  final retrieved = DateTime.utc(2026, 10, 25, 12, 1);
  AuthenticatedPortfolioViewPosition holding(
    String symbol, {
    String? exchange = 'NASDAQ',
    String currency = 'USD',
    String provider = 'yahoo_finance',
  }) => AuthenticatedPortfolioViewPosition(
    serverPositionId: symbol == 'AAPL' ? 1 : 2,
    symbol: symbol,
    companyName: symbol,
    exchange: exchange,
    quantity: 2,
    currency: currency,
    currentPrice: 100,
    averagePurchasePrice: null,
    currentValue: 200,
    investedValue: null,
    profitLoss: null,
    profitLossPercentage: null,
    marketSourceProvider: provider,
    marketObservedAt: observed,
    marketRetrievedAt: retrieved,
  );

  PortfolioInstrumentIdentity identity(String symbol, {
    String currency = 'USD',
    String exchange = 'NASDAQ',
    bool riskReady = true,
  }) => PortfolioInstrumentIdentity(
    databaseInstrumentId: symbol == 'AAPL' ? 1 : 2,
    canonicalInstrumentId: '$symbol@$exchange',
    issuerId: 'issuer:$symbol',
    symbol: symbol,
    exchange: exchange,
    exchangeShortName: exchange,
    currency: currency,
    sourceProvider: 'verified_catalog',
    retrievedAt: retrieved,
    resolutionMethod: 'symbol_and_exchange_exact',
    exchangeVerified: true,
    isRiskReady: riskReady,
    isWeightingReady: false,
    recommendationPolicy: 'no_advice',
    productionEligible: false,
    automaticTrading: false,
  );

  test('uses verified owner holdings and canonical PIT pair, never local cost', () async {
    var calls = 0;
    final service = AuthenticatedPortfolioCorrelationService(
      resolveIdentity: ({required symbol, exchange}) async {
        expect(exchange, 'NASDAQ');
        return identity(symbol);
      },
      loadPair: ({
        required leftInstrumentId,
        required rightInstrumentId,
        required sourceProvider,
        required knowledgeCutoff,
        observedFrom,
        observedTo,
      }) async {
        calls++;
        expect([leftInstrumentId, rightInstrumentId], [1, 2]);
        expect(sourceProvider, 'yahoo_finance');
        expect(knowledgeCutoff.isUtc, isTrue);
        return PortfolioPairCorrelation(
          leftInstrumentId: 1,
          rightInstrumentId: 2,
          sourceProvider: sourceProvider,
          knowledgeCutoff: knowledgeCutoff,
          sampleCount: 42,
          correlation: 0.4,
          firstReturnDate: DateTime.utc(2026, 8, 1),
          lastReturnDate: DateTime.utc(2026, 10, 24),
          latestRetrievedAt: retrieved,
          priceField: 'adjusted_close',
          alignmentPolicy: 'utc_calendar_date_intersection',
          returnPolicy: 'simple_return_consecutive_observations_per_instrument',
          recommendationPolicy: 'no_advice',
          productionEligible: false,
          allocationInfluence: false,
          automaticTrading: false,
        );
      },
    );
    final result = await service.analyze(
      positions: [holding('AAPL'), holding('MSFT')],
    );
    expect(result.meanCorrelation, 0.4);
    expect(result.minimumSampleCount, 42);
    expect(result.recommendationPolicy, 'no_advice');
    expect(result.allocationInfluence, isFalse);
    expect(calls, 1);
  });

  test('unverified exchange, currency or risk identity fails closed', () async {
    for (final invalid in [
      holding('AAPL', exchange: null),
      holding('AAPL', currency: 'EUR'),
    ]) {
      final service = AuthenticatedPortfolioCorrelationService(
        resolveIdentity: ({required symbol, exchange}) async => identity(symbol),
        loadPair: ({
          required leftInstrumentId,
          required rightInstrumentId,
          required sourceProvider,
          required knowledgeCutoff,
          observedFrom,
          observedTo,
        }) async => throw StateError('Should not query pair'),
      );
      await expectLater(
        service.analyze(positions: [invalid, holding('MSFT')]),
        throwsStateError,
      );
    }
  });

  test('duplicate canonical lots are analyzed as one exposure', () async {
    var calls = 0;
    final service = AuthenticatedPortfolioCorrelationService(
      resolveIdentity: ({required symbol, exchange}) async => identity(symbol),
      loadPair: ({
        required leftInstrumentId,
        required rightInstrumentId,
        required sourceProvider,
        required knowledgeCutoff,
        observedFrom,
        observedTo,
      }) async {
        calls++;
        return PortfolioPairCorrelation(
          leftInstrumentId: leftInstrumentId,
          rightInstrumentId: rightInstrumentId,
          sourceProvider: sourceProvider,
          knowledgeCutoff: knowledgeCutoff,
          sampleCount: 30,
          correlation: 0.2,
          firstReturnDate: DateTime.utc(2026, 8, 1),
          lastReturnDate: DateTime.utc(2026, 10, 24),
          latestRetrievedAt: retrieved,
          priceField: 'adjusted_close',
          alignmentPolicy: 'utc_calendar_date_intersection',
          returnPolicy: 'simple_return_consecutive_observations_per_instrument',
          recommendationPolicy: 'no_advice',
          productionEligible: false,
          allocationInfluence: false,
          automaticTrading: false,
        );
      },
    );
    final result = await service.analyze(
      positions: [holding('AAPL'), holding('AAPL'), holding('MSFT')],
    );
    expect(result.pairs.length, 1);
    expect(calls, 1);
  });

  test('mixed providers never reach pairwise correlation', () async {
    var calls = 0;
    final service = AuthenticatedPortfolioCorrelationService(
      resolveIdentity: ({required symbol, exchange}) async => identity(symbol),
      loadPair: ({
        required leftInstrumentId,
        required rightInstrumentId,
        required sourceProvider,
        required knowledgeCutoff,
        observedFrom,
        observedTo,
      }) async {
        calls++;
        throw StateError('No mixed-provider query allowed');
      },
    );
    await expectLater(
      service.analyze(positions: [
        holding('AAPL'),
        holding('MSFT', provider: 'stooq'),
      ]),
      throwsStateError,
    );
    expect(calls, 0);
  });
}
