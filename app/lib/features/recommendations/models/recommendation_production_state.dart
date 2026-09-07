class RecommendationProductionState {
  final DateTime asOf;
  final RecommendationProductionRecommendation? recommendation;
  final RecommendationProductionAllocation? allocation;
  final bool productionRecommendationAvailable;
  final bool productionAllocationAvailable;
  final bool automaticTrading;
  final bool readOnly;

  const RecommendationProductionState({
    required this.asOf,
    required this.recommendation,
    required this.allocation,
    required this.productionRecommendationAvailable,
    required this.productionAllocationAvailable,
    required this.automaticTrading,
    required this.readOnly,
  });

  bool get isSafe {
    if (!readOnly || automaticTrading) return false;
    if (productionRecommendationAvailable != (recommendation != null)) return false;
    if (productionAllocationAvailable != (allocation != null)) return false;
    if (allocation != null && recommendation == null) return false;
    return true;
  }
}

class RecommendationProductionRecommendation {
  final int instrumentId;
  final String symbol;
  final String action;
  final String policyState;
  final DateTime asOf;
  final DateTime authorizedAt;
  final String authorizationFingerprint;
  final String economicContractFingerprint;

  const RecommendationProductionRecommendation({
    required this.instrumentId,
    required this.symbol,
    required this.action,
    required this.policyState,
    required this.asOf,
    required this.authorizedAt,
    required this.authorizationFingerprint,
    required this.economicContractFingerprint,
  });
}

class RecommendationProductionAllocation {
  final int instrumentId;
  final String symbol;
  final String action;
  final DateTime asOf;
  final DateTime authorizedAt;
  final String authorizationFingerprint;
  final String recommendationAuthorizationFingerprint;
  final String economicContractFingerprint;
  final String baseCurrency;
  final double referenceCapital;
  final double targetAmountInBaseCurrency;
  final double deltaAmountInBaseCurrency;

  const RecommendationProductionAllocation({
    required this.instrumentId,
    required this.symbol,
    required this.action,
    required this.asOf,
    required this.authorizedAt,
    required this.authorizationFingerprint,
    required this.recommendationAuthorizationFingerprint,
    required this.economicContractFingerprint,
    required this.baseCurrency,
    required this.referenceCapital,
    required this.targetAmountInBaseCurrency,
    required this.deltaAmountInBaseCurrency,
  });
}
