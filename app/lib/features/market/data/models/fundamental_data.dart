/// Datos fundamentales de una empresa.
///
/// Representa información financiera normalizada independientemente
/// del proveedor que la haya proporcionado.
class FundamentalData {
  final String symbol;
  final String? companyName;

  final double? revenue;
  final double? ebit;
  final double? ebitda;
  final double? netIncome;

  final double? totalAssets;
  final double? totalDebt;
  final double? cashAndEquivalents;

  final double? operatingCashFlow;
  final double? capitalExpenditure;

  final DateTime? periodEnd;
  final String? periodType;

  final String providerId;

  const FundamentalData({
    required this.symbol,
    required this.providerId,
    this.companyName,
    this.revenue,
    this.ebit,
    this.ebitda,
    this.netIncome,
    this.totalAssets,
    this.totalDebt,
    this.cashAndEquivalents,
    this.operatingCashFlow,
    this.capitalExpenditure,
    this.periodEnd,
    this.periodType,
  });
}