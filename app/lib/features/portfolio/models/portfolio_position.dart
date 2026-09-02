class PortfolioPosition {
  final String symbol;
  final String companyName;
  final double shares;
  final double averagePrice;
  final double currentPrice;
  final DateTime? currentPriceUpdatedAt;

  const PortfolioPosition({
    required this.symbol,
    required this.companyName,
    required this.shares,
    required this.averagePrice,
    required this.currentPrice,
    this.currentPriceUpdatedAt,
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
    DateTime? currentPriceUpdatedAt,
  }) {
    return PortfolioPosition(
      symbol: symbol ?? this.symbol,
      companyName: companyName ?? this.companyName,
      shares: shares ?? this.shares,
      averagePrice: averagePrice ?? this.averagePrice,
      currentPrice: currentPrice ?? this.currentPrice,
      currentPriceUpdatedAt:
          currentPriceUpdatedAt ?? this.currentPriceUpdatedAt,
    );
  }

  Map<String, dynamic> toMap() {
    return {
      'symbol': symbol,
      'companyName': companyName,
      'shares': shares,
      'averagePrice': averagePrice,
      'currentPrice': currentPrice,
      'currentPriceUpdatedAt': currentPriceUpdatedAt?.toIso8601String(),
    };
  }

  factory PortfolioPosition.fromMap(Map<String, dynamic> map) {
    final updatedAtRaw = map['currentPriceUpdatedAt'];

    return PortfolioPosition(
      symbol: map['symbol'] as String,
      companyName: map['companyName'] as String,
      shares: (map['shares'] as num).toDouble(),
      averagePrice: (map['averagePrice'] as num).toDouble(),
      currentPrice: (map['currentPrice'] as num).toDouble(),
      currentPriceUpdatedAt: updatedAtRaw == null
          ? null
          : DateTime.tryParse(updatedAtRaw.toString()),
    );
  }

  Map<String, dynamic> toJson() {
    return toMap();
  }

  factory PortfolioPosition.fromJson(Map<String, dynamic> json) {
    return PortfolioPosition.fromMap(json);
  }
}
