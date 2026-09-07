class RecommendationProductionState {
  static const _actions = {'buy', 'hold', 'reduce', 'sell'};
  static final RegExp _sha256Pattern = RegExp(r'^[0-9a-f]{64}$');
  static final RegExp _currencyPattern = RegExp(r'^[A-Z]{3}$');

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
    if (!asOf.isUtc || !readOnly || automaticTrading) return false;
    if (productionRecommendationAvailable != (recommendation != null)) return false;
    if (productionAllocationAvailable != (allocation != null)) return false;

    final recommendationValue = recommendation;
    if (recommendationValue != null &&
        !_recommendationIsSafe(recommendationValue)) {
      return false;
    }

    final allocationValue = allocation;
    if (allocationValue != null) {
      if (recommendationValue == null ||
          !_allocationIsSafe(allocationValue, recommendationValue)) {
        return false;
      }
    }
    return true;
  }

  bool _recommendationIsSafe(
    RecommendationProductionRecommendation value,
  ) {
    if (value.instrumentId <= 0 || value.symbol.trim().isEmpty) return false;
    if (!_actions.contains(value.action)) return false;
    if (value.policyState.trim().isEmpty) return false;
    if (!value.asOf.isUtc || !value.authorizedAt.isUtc) return false;
    if (value.asOf.isAfter(asOf) || value.authorizedAt.isAfter(asOf)) return false;
    if (value.authorizedAt.isBefore(value.asOf)) return false;
    if (!_isSha256(value.authorizationFingerprint) ||
        !_isSha256(value.economicContractFingerprint)) {
      return false;
    }
    return true;
  }

  bool _allocationIsSafe(
    RecommendationProductionAllocation value,
    RecommendationProductionRecommendation recommendationValue,
  ) {
    if (value.instrumentId <= 0 || value.symbol.trim().isEmpty) return false;
    if (!_actions.contains(value.action)) return false;
    if (!value.asOf.isUtc || !value.authorizedAt.isUtc) return false;
    if (value.asOf.isAfter(asOf) || value.authorizedAt.isAfter(asOf)) return false;
    if (value.authorizedAt.isBefore(value.asOf) ||
        value.authorizedAt.isBefore(recommendationValue.authorizedAt)) {
      return false;
    }
    if (value.instrumentId != recommendationValue.instrumentId ||
        value.symbol != recommendationValue.symbol ||
        value.action != recommendationValue.action ||
        value.asOf != recommendationValue.asOf ||
        value.recommendationAuthorizationFingerprint !=
            recommendationValue.authorizationFingerprint ||
        value.economicContractFingerprint !=
            recommendationValue.economicContractFingerprint) {
      return false;
    }
    if (!_isSha256(value.authorizationFingerprint) ||
        !_isSha256(value.recommendationAuthorizationFingerprint) ||
        !_isSha256(value.economicContractFingerprint)) {
      return false;
    }
    if (!_currencyPattern.hasMatch(value.baseCurrency)) return false;
    if (!value.referenceCapital.isFinite || value.referenceCapital <= 0) {
      return false;
    }
    if (!value.targetAmountInBaseCurrency.isFinite ||
        value.targetAmountInBaseCurrency < 0) {
      return false;
    }
    if (!value.deltaAmountInBaseCurrency.isFinite) return false;
    return true;
  }

  bool _isSha256(String value) =>
      _sha256Pattern.hasMatch(value.trim().toLowerCase());
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
