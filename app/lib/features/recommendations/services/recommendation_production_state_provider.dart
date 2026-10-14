import '../models/recommendation_production_state.dart';

abstract class RecommendationProductionStateProvider {
  Future<RecommendationProductionState> getLatest({
    DateTime? asOf,
    String? symbol,
    int? instrumentId,
  });
}
