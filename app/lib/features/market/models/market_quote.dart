class MarketQuote {
  final String symbol;
  final String companyName;
  final double currentPrice;
  final double change;
  final double changePercentage;
  final double? marketCap;
  final String? currency;
  final String? exchange;
  final String? quoteType;
  final String? exchangeTimezone;
  final DateTime updatedAt;
  final String? sourceProvider;
  final DateTime? retrievedAt;
  final String? quoteMode;
  final String? priceSessionDate;
  final bool? realTimePriceVerified;
  final bool? historicalPointInTimeEligible;
  final int? instrumentId;
  final String? canonicalIdentityStatus;

  const MarketQuote({
    required this.symbol,
    required this.companyName,
    required this.currentPrice,
    required this.change,
    required this.changePercentage,
    this.marketCap,
    this.currency,
    this.exchange,
    this.quoteType,
    this.exchangeTimezone,
    required this.updatedAt,
    this.sourceProvider,
    this.retrievedAt,
    this.quoteMode,
    this.priceSessionDate,
    this.realTimePriceVerified,
    this.historicalPointInTimeEligible,
    this.instrumentId,
    this.canonicalIdentityStatus,
  });

  bool get isPositive => change > 0;

  bool get isNegative => change < 0;

  bool get isUnchanged => change == 0;

  Map<String, dynamic> toMap() {
    return {
      'symbol': symbol,
      'companyName': companyName,
      'currentPrice': currentPrice,
      'change': change,
      'changePercentage': changePercentage,
      'marketCap': marketCap,
      'currency': currency,
      'exchange': exchange,
      'quoteType': quoteType,
      'exchangeTimezone': exchangeTimezone,
      'updatedAt': updatedAt.toIso8601String(),
      'sourceProvider': sourceProvider,
      'retrievedAt': retrievedAt?.toIso8601String(),
      'quoteMode': quoteMode,
      'priceSessionDate': priceSessionDate,
      'realTimePriceVerified': realTimePriceVerified,
      'historicalPointInTimeEligible': historicalPointInTimeEligible,
      'instrumentId': instrumentId,
      'canonicalIdentityStatus': canonicalIdentityStatus,
    };
  }

  factory MarketQuote.fromMap(Map<String, dynamic> map) {
    final retrievedAtRaw = map['retrievedAt'];
    final status = map['canonicalIdentityStatus'];
    final id = map['instrumentId'];
    if (status != null &&
        status != 'unresolved' &&
        status != 'matched_internal_listing') {
      throw const FormatException('Estado de identidad de mercado desconocido.');
    }
    if ((id != null &&
            (id is! int || id <= 0 || status != 'matched_internal_listing')) ||
        (status == 'matched_internal_listing' && id == null)) {
      throw const FormatException('Identidad interna de mercado contradictoria.');
    }

    return MarketQuote(
      symbol: map['symbol'] as String,
      companyName: map['companyName'] as String,
      currentPrice: (map['currentPrice'] as num).toDouble(),
      change: (map['change'] as num).toDouble(),
      changePercentage: (map['changePercentage'] as num).toDouble(),
      marketCap: (map['marketCap'] as num?)?.toDouble(),
      currency: map['currency']?.toString(),
      exchange: map['exchange']?.toString(),
      quoteType: map['quoteType']?.toString(),
      exchangeTimezone: map['exchangeTimezone']?.toString(),
      updatedAt: DateTime.parse(map['updatedAt'] as String),
      sourceProvider: map['sourceProvider']?.toString(),
      quoteMode: map['quoteMode']?.toString(),
      priceSessionDate: map['priceSessionDate']?.toString(),
      realTimePriceVerified: map['realTimePriceVerified'] is bool
          ? map['realTimePriceVerified'] as bool : null,
      historicalPointInTimeEligible: map['historicalPointInTimeEligible'] is bool
          ? map['historicalPointInTimeEligible'] as bool : null,
      instrumentId: id as int?,
      canonicalIdentityStatus: status as String?,
      retrievedAt: retrievedAtRaw == null
          ? null
          : DateTime.tryParse(retrievedAtRaw.toString()),
    );
  }

  Map<String, dynamic> toJson() {
    return toMap();
  }

  factory MarketQuote.fromJson(Map<String, dynamic> json) {
    return MarketQuote.fromMap(json);
  }
}
