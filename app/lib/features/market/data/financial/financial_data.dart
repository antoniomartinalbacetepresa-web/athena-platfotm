class FinancialData {
  final String symbol;
  final String? companyName;
  final String? currency;
  final DateTime? periodEnd;
  final String? periodType;

  final double? revenue;
  final double? ebitda;
  final double? ebit;
  final double? netIncome;
  final double? eps;

  final double? cash;
  final double? totalDebt;

  final double? grossMargin;
  final double? operatingMargin;
  final double? netMargin;

  final double? operatingCashFlow;
  final double? freeCashFlow;

  final String providerId;

  const FinancialData({
    required this.symbol,
    required this.providerId,
    this.companyName,
    this.currency,
    this.periodEnd,
    this.periodType,
    this.revenue,
    this.ebitda,
    this.ebit,
    this.netIncome,
    this.eps,
    this.cash,
    this.totalDebt,
    this.grossMargin,
    this.operatingMargin,
    this.netMargin,
    this.operatingCashFlow,
    this.freeCashFlow,
  });
}
