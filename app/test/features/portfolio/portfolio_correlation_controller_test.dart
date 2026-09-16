import 'dart:async';

import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/portfolio/models/portfolio_correlation_snapshot.dart';
import 'package:app/features/portfolio/models/portfolio_pair_correlation.dart';
import 'package:app/features/portfolio/models/portfolio_position.dart';
import 'package:app/features/portfolio/presentation/controllers/portfolio_correlation_controller.dart';
import 'package:app/features/portfolio/services/portfolio_correlation_evidence_service.dart';

PortfolioPosition position(String symbol, int id) => PortfolioPosition(
      symbol: symbol,
      companyName: symbol,
      shares: 1,
      averagePrice: 100,
      currentPrice: 101,
      priceCurrency: 'USD',
      exchange: 'NMS',
      currentPriceUpdatedAt: DateTime.utc(2026, 9, 4, 17),
      currentPriceSourceProvider: 'yahoo',
      currentPriceRetrievedAt: DateTime.utc(2026, 9, 4, 17, 1),
      databaseInstrumentId: id,
      canonicalInstrumentId: '$symbol@NMS',
      canonicalIssuerId: 'issuer:$symbol',
      identitySourceProvider: 'yahoo_catalog',
      identityRetrievedAt: DateTime.utc(2026, 9, 4, 17, 2),
      identityResolutionMethod: 'symbol_and_exchange_exact',
      identityExchangeVerified: true,
      identityRiskReady: true,
    );

PortfolioPairCorrelation pair(int left, int right, DateTime cutoff, double value) =>
    PortfolioPairCorrelation(
      leftInstrumentId: left,
      rightInstrumentId: right,
      sourceProvider: 'yahoo',
      knowledgeCutoff: cutoff,
      sampleCount: 10,
      correlation: value,
      firstReturnDate: DateTime.utc(2026, 8, 1),
      lastReturnDate: DateTime.utc(2026, 9, 1),
      latestRetrievedAt: cutoff.subtract(const Duration(seconds: 1)),
      priceField: 'adjusted_close',
      alignmentPolicy: 'utc_calendar_date_intersection',
      returnPolicy: 'simple_return_consecutive_observations_per_instrument',
      recommendationPolicy: 'no_advice',
      productionEligible: false,
      allocationInfluence: false,
      automaticTrading: false,
    );

void main() {
  test('loads verified correlation and clears for a single position', () async {
    final cutoff = DateTime.utc(2026, 9, 4, 18);
    final controller = PortfolioCorrelationController(
      service: PortfolioCorrelationEvidenceService(
        loadPair: ({
          required leftInstrumentId,
          required rightInstrumentId,
          required sourceProvider,
          required knowledgeCutoff,
          observedFrom,
          observedTo,
        }) async => pair(leftInstrumentId, rightInstrumentId, cutoff, 0.4),
      ),
    );

    await controller.load(
      positions: [position('AAA', 1), position('BBB', 2)],
      knowledgeCutoff: cutoff,
    );
    expect(controller.snapshot?.meanCorrelation, 0.4);
    expect(controller.error, isNull);

    await controller.load(
      positions: [position('AAA', 1)],
      knowledgeCutoff: cutoff,
    );
    expect(controller.snapshot, isNull);
    expect(controller.error, isNull);
  });

  test('fails closed without exposing partial snapshot', () async {
    final cutoff = DateTime.utc(2026, 9, 4, 18);
    final controller = PortfolioCorrelationController(
      service: PortfolioCorrelationEvidenceService(
        loadPair: ({
          required leftInstrumentId,
          required rightInstrumentId,
          required sourceProvider,
          required knowledgeCutoff,
          observedFrom,
          observedTo,
        }) async => throw StateError('history missing'),
      ),
    );

    await controller.load(
      positions: [position('AAA', 1), position('BBB', 2)],
      knowledgeCutoff: cutoff,
    );

    expect(controller.snapshot, isNull);
    expect(controller.error, isNotNull);
    expect(controller.isLoading, isFalse);
  });

  test('older async result cannot overwrite a newer request', () async {
    final cutoff = DateTime.utc(2026, 9, 4, 18);
    final first = Completer<PortfolioPairCorrelation>();
    var calls = 0;
    final service = PortfolioCorrelationEvidenceService(
      loadPair: ({
        required leftInstrumentId,
        required rightInstrumentId,
        required sourceProvider,
        required knowledgeCutoff,
        observedFrom,
        observedTo,
      }) {
        calls++;
        if (calls == 1) return first.future;
        return Future.value(pair(leftInstrumentId, rightInstrumentId, cutoff, -0.2));
      },
    );
    final controller = PortfolioCorrelationController(service: service);

    final oldLoad = controller.load(
      positions: [position('AAA', 1), position('BBB', 2)],
      knowledgeCutoff: cutoff,
    );
    await controller.load(
      positions: [position('CCC', 3), position('DDD', 4)],
      knowledgeCutoff: cutoff,
    );
    expect(controller.snapshot?.meanCorrelation, -0.2);

    first.complete(pair(1, 2, cutoff, 0.9));
    await oldLoad;
    expect(controller.snapshot?.meanCorrelation, -0.2);
  });
}
