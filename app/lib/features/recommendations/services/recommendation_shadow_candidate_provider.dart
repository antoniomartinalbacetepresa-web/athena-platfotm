import '../models/recommendation_shadow_candidate_snapshot.dart';

abstract class RecommendationShadowCandidateProvider {
  Future<RecommendationShadowCandidateSnapshot> getLatest({DateTime? asOf});
}
