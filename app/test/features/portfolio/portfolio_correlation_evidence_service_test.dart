import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/portfolio/models/portfolio_pair_correlation.dart';
import 'package:app/features/portfolio/models/portfolio_position.dart';
import 'package:app/features/portfolio/services/portfolio_correlation_evidence_service.dart';

PortfolioPosition verifiedPosition(String symbol, int id, {String provider = 'yahoo'}) {
  return PortfolioPosition(
    symbol: symbol,
    companyName: '$symbol Company',
    shares: 1,
    averagePrice: 100,
    currentPrice: 110,
    priceCurrency: 'USD',
    exchange: 'NMS',
    currentPriceUpdatedAt: DateTime.utc(2026, 9, 4, 17),
    currentPriceSourceProvider: provider,
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
}

PortfolioPairCorrelation pair(
  int left,
  int right,
  double correlation,
  DateTime cutoff, {
  int sampleCount = 20,
  String provider = 'yahoo',
}) {
  return PortfolioPairCorrelation(
    leftInstrumentId: left,
    rightInstrumentId: right,
    sourceProvider: provider,
    knowledgeCutoff: cutoff,
    sampleCount: sampleCount,
    correlation: correlation,
    firstReturnDate: DateTime.utc(2026, 8, 1),
    lastReturnDate: DateTime.utc(2026, 9, 1),
    latestRetrievedAt: cutoff.subtract(const Duration(minutes: 1)),
    priceField: 'adjusted_close',
    alignmentPolicy: 'utc_calendar_date_intersection',
    returnPolicy: 'simple_return_consecutive_observations_per_instrument',
    recommendationPolicy: 'no_advice',
    productionEligible: false,
    allocationInfluence: false,
    automaticTrading: false,
  );
}

void main() {
  test('builds all canonical pairs and descriptive aggregate only', () async {
    final cutoff = DateTime.utc(2026, 9, 4, 18);
    final requested = <String>[];
    final service = PortfolioCorrelationEvidenceService(
      loadPair: ({
        required leftInstrumentId,
        required rightInstrumentId,
        required sourceProvider,
        required knowledgeCutoff,
        observedFrom,
        observedTo,
      }) async {
        requested.add('$leftInstrumentId-$rightInstrumentId');
        final value = <String, double>{
          '1-2': 0.2,
          '1-3': -0.1,
          '2-3': 0.5,
        }['$leftInstrumentId-$rightInstrumentId']!;
        return pair(leftInstrumentId, rightInstrumentId, value, cutoff);
      },
    );

    final snapshot = await service.analyze(
      positions: [
        verifiedPosition('AAA', 1),
        verifiedPosition('BBB', 2),
        verifiedPosition('CCC', 3),
      ],
      knowledgeCutoff: cutoff,
    );

    expect(requested, ['1-2', '1-3', '2-3']);
    expect(snapshot.pairs, hasLength(3));
    expect(snapshot.meanCorrelation, closeTo(0.2, 1e-12));
    expect(snapshot.minimumCorrelation, -0.1);
    expect(snapshot.maximumCorrelation, 0.5);
    expect(snapshot.minimumSampleCount, 20);
    expect(snapshot.recommendationPolicy, 'no_advice');
    expect(snapshot.productionEligible, isFalse);
    expect(snapshot.allocationInfluence, isFalse);
    expect(snapshot.automaticTrading, isFalse);
  });

  test('fails closed for legacy position without canonical identity', () async {
    final cutoff = DateTime.utc(2026, 9, 4, 18);
    final legacy = PortfolioPosition(
      symbol: 'OLD',
      companyName: 'Legacy',
      shares: 1,
      averagePrice: 10,
      currentPrice: 11,
      priceCurrency: 'USD',
      exchange: 'NMS',
      currentPriceUpdatedAt: DateTime.utc(2026, 9, 4, 17),
      currentPriceSourceProvider: 'yahoo',
      currentPriceRetrievedAt: DateTime.utc(2026, 9, 4, 17, 1),
    );
    final service = PortfolioCorrelationEvidenceService(
      loadPair: ({
        required leftInstrumentId,
        required rightInstrumentId,
        required sourceProvider,
        required knowledgeCutoff,
        observedFrom,
        observedTo,
      }) async => pair(leftInstrumentId, rightInstrumentId, 0.2, cutoff),
    );

    await expectLater(
      service.analyze(
        positions: [verifiedPosition('AAA', 1), legacy],
        knowledgeCutoff: cutoff,
      ),
      throwsStateError,
    );
  });

  test('fails closed for duplicate canonical id or mixed providers', () async {
    final cutoff = DateTime.utc(2026, 9, 4, 18);
    final service = PortfolioCorrelationEvidenceService(
      loadPair: ({
        required leftInstrumentId,
        required rightInstrumentId,
        required sourceProvider,
        required knowledgeCutoff,
        observedFrom,
        observedTo,
      }) async => pair(leftInstrumentId, rightInstrumentId, 0.2, cutoff),
    );

    await expectLater(
      service.analyze(
        positions: [verifiedPosition('AAA', 1), verifiedPosition('BBB', 1)],
        knowledgeCutoff: cutoff,
      ),
      throwsStateError,
    );
    await expectLater(
      service.analyze(
        positions: [
          verifiedPosition('AAA', 1),
          verifiedPosition('BBB', 2, provider: 'other'),
        ],
        knowledgeCutoff: cutoff,
      ),
      throwsStateError,
    );
  });

  test('rejects pair evidence whose cutoff or provider drifts', () async {
    final cutoff = DateTime.utc(2026, 9, 4, 18);

    for (final wrongProvider in [false, true]) {
      final service = PortfolioCorrelationEvidenceService(
        loadPair: ({
          required leftInstrumentId,
          required rightInstrumentId,
          required sourceProvider,
          required knowledgeCutoff,
          observedFrom,
          observedTo,
        }) async => pair(
          leftInstrumentId,
          rightInstrumentId,
          0.2,
          wrongProvider ? cutoff : cutoff.add(const Duration(seconds: 1)),
          provider: wrongProvider ? 'other' : 'yahoo',
        ),
      );

      await expectLater(
        service.analyze(
          positions: [verifiedPosition('AAA', 1), verifiedPosition('BBB', 2)],
          knowledgeCutoff: cutoff,
        ),
        throwsStateError,
      );
    }
  });
}
