import 'portfolio_pair_correlation.dart';

class PortfolioCorrelationSnapshot {
  final List<PortfolioPairCorrelation> pairs;
  final String sourceProvider;
  final DateTime knowledgeCutoff;
  final double meanCorrelation;
  final double minimumCorrelation;
  final double maximumCorrelation;
  final int minimumSampleCount;
  final DateTime latestRetrievedAt;

  const PortfolioCorrelationSnapshot({
    required this.pairs,
    required this.sourceProvider,
    required this.knowledgeCutoff,
    required this.meanCorrelation,
    required this.minimumCorrelation,
    required this.maximumCorrelation,
    required this.minimumSampleCount,
    required this.latestRetrievedAt,
  });

  String get recommendationPolicy => 'no_advice';
  bool get productionEligible => false;
  bool get allocationInfluence => false;
  bool get automaticTrading => false;
}
