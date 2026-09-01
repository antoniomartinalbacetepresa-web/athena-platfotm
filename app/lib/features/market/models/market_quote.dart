class MarketQuote {
  final String symbol;
  final String companyName;
  final double currentPrice;
  final double change;
  final double changePercentage;
  final double? marketCap;
  final DateTime updatedAt;

  const MarketQuote({
    required this.symbol,
    required this.companyName,
    required this.currentPrice,
    required this.change,
    required this.changePercentage,
    this.marketCap,
    required this.updatedAt,
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
      'updatedAt': updatedAt.toIso8601String(),
    };
  }

  factory MarketQuote.fromMap(Map<String, dynamic> map) {
    return MarketQuote(
      symbol: map['symbol'] as String,
      companyName: map['companyName'] as String,
      currentPrice: (map['currentPrice'] as num).toDouble(),
      change: (map['change'] as num).toDouble(),
      changePercentage:
          (map['changePercentage'] as num).toDouble(),
      marketCap: (map['marketCap'] as num?)?.toDouble(),
      updatedAt: DateTime.parse(
        map['updatedAt'] as String,
      ),
    );
  }

  Map<String, dynamic> toJson() {
    return toMap();
  }

  factory MarketQuote.fromJson(Map<String, dynamic> json) {
    return MarketQuote.fromMap(json);
  }
}