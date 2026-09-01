class PortfolioPosition {
  final String symbol;
  final String companyName;
  final double shares;
  final double averagePrice;
  final double currentPrice;

  const PortfolioPosition({
    required this.symbol,
    required this.companyName,
    required this.shares,
    required this.averagePrice,
    required this.currentPrice,
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

  // ============================================================
  // MAP
  // ============================================================

  Map<String, dynamic> toMap() {
    return {
      'symbol': symbol,
      'companyName': companyName,
      'shares': shares,
      'averagePrice': averagePrice,
      'currentPrice': currentPrice,
    };
  }

  factory PortfolioPosition.fromMap(
    Map<String, dynamic> map,
  ) {
    return PortfolioPosition(
      symbol: map['symbol'] as String,
      companyName: map['companyName'] as String,
      shares: (map['shares'] as num).toDouble(),
      averagePrice: (map['averagePrice'] as num).toDouble(),
      currentPrice: (map['currentPrice'] as num).toDouble(),
    );
  }

  // ============================================================
  // JSON
  // ============================================================

  Map<String, dynamic> toJson() {
    return toMap();
  }

  factory PortfolioPosition.fromJson(
    Map<String, dynamic> json,
  ) {
    return PortfolioPosition.fromMap(json);
  }
}