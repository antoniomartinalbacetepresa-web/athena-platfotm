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
  });

  double get investedValue {
    return shares * averagePrice;
  }

  double get currentValue {
    return shares * currentPrice;
  }

  double get profitLoss {
    return currentValue - investedValue;
  }

  double get profitLossPercentage {
    if (investedValue == 0) {
      return 0;
    }

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
      currentPriceUpdatedAt:
          currentPriceUpdatedAt ?? this.currentPriceUpdatedAt,
      currentPriceSourceProvider:
          currentPriceSourceProvider ?? this.currentPriceSourceProvider,
      currentPriceRetrievedAt:
          currentPriceRetrievedAt ?? this.currentPriceRetrievedAt,
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
    };
  }

  factory PortfolioPosition.fromMap(Map<String, dynamic> map) {
    final costBasisDateRaw = map['costBasisDate'];
    final updatedAtRaw = map['currentPriceUpdatedAt'];
    final retrievedAtRaw = map['currentPriceRetrievedAt'];

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
    );
  }

  Map<String, dynamic> toJson() {
    return toMap();
  }

  factory PortfolioPosition.fromJson(Map<String, dynamic> json) {
    return PortfolioPosition.fromMap(json);
  }
}
