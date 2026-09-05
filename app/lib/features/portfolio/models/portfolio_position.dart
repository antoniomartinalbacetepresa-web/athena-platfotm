import 'athena_portfolio_policy_state.dart';

class PortfolioPosition {
  final String symbol;
  final String companyName;
  final double shares;
  final double averagePrice;
  final double currentPrice;
  final DateTime? costBasisDate;
  final String? priceCurrency;
  final String? exchange;
  final String? quoteType;
  final DateTime? currentPriceUpdatedAt;
  final String? currentPriceSourceProvider;
  final DateTime? currentPriceRetrievedAt;

  /// Canonical identity is persisted only after the backend resolves the
  /// position against a verified listing. Legacy positions remain readable
  /// with these fields null and are therefore not risk/correlation ready.
  final int? databaseInstrumentId;
  final String? canonicalInstrumentId;
  final String? canonicalIssuerId;
  final String? identitySourceProvider;
  final DateTime? identityRetrievedAt;
  final String? identityResolutionMethod;
  final bool identityExchangeVerified;
  final bool identityRiskReady;

  /// Explicit state used by ATHENA's validated action-policy layer.
  ///
  /// This is deliberately nullable. Legacy positions and positions for which
  /// the user has not explicitly classified the intended ATHENA exposure must
  /// remain unclassified; ATHENA must never infer reduced_long/full_long from
  /// shares, value, or an implicit percentage threshold.
  final AthenaPortfolioPolicyState? athenaPolicyState;

  const PortfolioPosition({
    required this.symbol,
    required this.companyName,
    required this.shares,
    required this.averagePrice,
    required this.currentPrice,
    this.costBasisDate,
    this.priceCurrency,
    this.exchange,
    this.quoteType,
    this.currentPriceUpdatedAt,
    this.currentPriceSourceProvider,
    this.currentPriceRetrievedAt,
    this.databaseInstrumentId,
    this.canonicalInstrumentId,
    this.canonicalIssuerId,
    this.identitySourceProvider,
    this.identityRetrievedAt,
    this.identityResolutionMethod,
    this.identityExchangeVerified = false,
    this.identityRiskReady = false,
    this.athenaPolicyState,
  });

  bool get hasVerifiedCanonicalIdentity =>
      databaseInstrumentId != null &&
      databaseInstrumentId! > 0 &&
      canonicalInstrumentId != null &&
      canonicalInstrumentId!.trim().isNotEmpty &&
      canonicalIssuerId != null &&
      canonicalIssuerId!.trim().isNotEmpty &&
      identitySourceProvider != null &&
      identitySourceProvider!.trim().isNotEmpty &&
      identityRetrievedAt != null &&
      identityResolutionMethod != null &&
      identityResolutionMethod!.trim().isNotEmpty &&
      identityExchangeVerified &&
      identityRiskReady;

  bool get hasExplicitAthenaPolicyState => athenaPolicyState != null;

  double get investedValue => shares * averagePrice;

  double get currentValue => shares * currentPrice;

  double get profitLoss => currentValue - investedValue;

  double get profitLossPercentage {
    if (investedValue == 0) return 0;
    return (profitLoss / investedValue) * 100;
  }

  PortfolioPosition copyWith({
    String? symbol,
    String? companyName,
    double? shares,
    double? averagePrice,
    double? currentPrice,
    DateTime? costBasisDate,
    String? priceCurrency,
    String? exchange,
    String? quoteType,
    DateTime? currentPriceUpdatedAt,
    String? currentPriceSourceProvider,
    DateTime? currentPriceRetrievedAt,
    int? databaseInstrumentId,
    String? canonicalInstrumentId,
    String? canonicalIssuerId,
    String? identitySourceProvider,
    DateTime? identityRetrievedAt,
    String? identityResolutionMethod,
    bool? identityExchangeVerified,
    bool? identityRiskReady,
    AthenaPortfolioPolicyState? athenaPolicyState,
    bool clearAthenaPolicyState = false,
  }) {
    return PortfolioPosition(
      symbol: symbol ?? this.symbol,
      companyName: companyName ?? this.companyName,
      shares: shares ?? this.shares,
      averagePrice: averagePrice ?? this.averagePrice,
      currentPrice: currentPrice ?? this.currentPrice,
      costBasisDate: costBasisDate ?? this.costBasisDate,
      priceCurrency: priceCurrency ?? this.priceCurrency,
      exchange: exchange ?? this.exchange,
      quoteType: quoteType ?? this.quoteType,
      currentPriceUpdatedAt: currentPriceUpdatedAt ?? this.currentPriceUpdatedAt,
      currentPriceSourceProvider:
          currentPriceSourceProvider ?? this.currentPriceSourceProvider,
      currentPriceRetrievedAt:
          currentPriceRetrievedAt ?? this.currentPriceRetrievedAt,
      databaseInstrumentId: databaseInstrumentId ?? this.databaseInstrumentId,
      canonicalInstrumentId:
          canonicalInstrumentId ?? this.canonicalInstrumentId,
      canonicalIssuerId: canonicalIssuerId ?? this.canonicalIssuerId,
      identitySourceProvider:
          identitySourceProvider ?? this.identitySourceProvider,
      identityRetrievedAt: identityRetrievedAt ?? this.identityRetrievedAt,
      identityResolutionMethod:
          identityResolutionMethod ?? this.identityResolutionMethod,
      identityExchangeVerified:
          identityExchangeVerified ?? this.identityExchangeVerified,
      identityRiskReady: identityRiskReady ?? this.identityRiskReady,
      athenaPolicyState: clearAthenaPolicyState
          ? null
          : (athenaPolicyState ?? this.athenaPolicyState),
    );
  }

  Map<String, dynamic> toMap() {
    return {
      'symbol': symbol,
      'companyName': companyName,
      'shares': shares,
      'averagePrice': averagePrice,
      'currentPrice': currentPrice,
      'costBasisDate': costBasisDate?.toUtc().toIso8601String(),
      'priceCurrency': priceCurrency,
      'exchange': exchange,
      'quoteType': quoteType,
      'currentPriceUpdatedAt': currentPriceUpdatedAt?.toIso8601String(),
      'currentPriceSourceProvider': currentPriceSourceProvider,
      'currentPriceRetrievedAt': currentPriceRetrievedAt?.toIso8601String(),
      'databaseInstrumentId': databaseInstrumentId,
      'canonicalInstrumentId': canonicalInstrumentId,
      'canonicalIssuerId': canonicalIssuerId,
      'identitySourceProvider': identitySourceProvider,
      'identityRetrievedAt': identityRetrievedAt?.toUtc().toIso8601String(),
      'identityResolutionMethod': identityResolutionMethod,
      'identityExchangeVerified': identityExchangeVerified,
      'identityRiskReady': identityRiskReady,
      'athenaPolicyState': athenaPolicyState?.key,
    };
  }

  factory PortfolioPosition.fromMap(Map<String, dynamic> map) {
    final costBasisDateRaw = map['costBasisDate'];
    final updatedAtRaw = map['currentPriceUpdatedAt'];
    final retrievedAtRaw = map['currentPriceRetrievedAt'];
    final identityRetrievedAtRaw = map['identityRetrievedAt'];
    final databaseInstrumentIdRaw = map['databaseInstrumentId'];

    return PortfolioPosition(
      symbol: map['symbol'] as String,
      companyName: map['companyName'] as String,
      shares: (map['shares'] as num).toDouble(),
      averagePrice: (map['averagePrice'] as num).toDouble(),
      currentPrice: (map['currentPrice'] as num).toDouble(),
      costBasisDate: costBasisDateRaw == null
          ? null
          : DateTime.tryParse(costBasisDateRaw.toString())?.toUtc(),
      priceCurrency: map['priceCurrency']?.toString(),
      exchange: map['exchange']?.toString(),
      quoteType: map['quoteType']?.toString(),
      currentPriceUpdatedAt: updatedAtRaw == null
          ? null
          : DateTime.tryParse(updatedAtRaw.toString()),
      currentPriceSourceProvider:
          map['currentPriceSourceProvider']?.toString(),
      currentPriceRetrievedAt: retrievedAtRaw == null
          ? null
          : DateTime.tryParse(retrievedAtRaw.toString()),
      databaseInstrumentId: databaseInstrumentIdRaw is int &&
              databaseInstrumentIdRaw > 0
          ? databaseInstrumentIdRaw
          : null,
      canonicalInstrumentId: map['canonicalInstrumentId']?.toString(),
      canonicalIssuerId: map['canonicalIssuerId']?.toString(),
      identitySourceProvider: map['identitySourceProvider']?.toString(),
      identityRetrievedAt: identityRetrievedAtRaw == null
          ? null
          : DateTime.tryParse(identityRetrievedAtRaw.toString())?.toUtc(),
      identityResolutionMethod: map['identityResolutionMethod']?.toString(),
      identityExchangeVerified: map['identityExchangeVerified'] == true,
      identityRiskReady: map['identityRiskReady'] == true,
      athenaPolicyState: AthenaPortfolioPolicyState.tryParse(
        map['athenaPolicyState'],
      ),
    );
  }

  Map<String, dynamic> toJson() => toMap();

  factory PortfolioPosition.fromJson(Map<String, dynamic> json) =>
      PortfolioPosition.fromMap(json);
}
