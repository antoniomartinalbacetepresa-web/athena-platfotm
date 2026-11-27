import 'market_data_point.dart';

/// Local replay metadata; no provider rights or historical publication claim.
class PersistedMarketHistory {
  final List<MarketDataPoint> points;
  final DateTime asOf;
  final bool truncated;

  PersistedMarketHistory({
    required List<MarketDataPoint> points,
    required this.asOf,
    required this.truncated,
  }) : points = List.unmodifiable(points);
}
