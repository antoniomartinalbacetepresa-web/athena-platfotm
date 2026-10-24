import '../services/authenticated_portfolio_service.dart';

/// UI-safe projection of an owner-scoped authenticated holding joined with a
/// verified market quote.
///
/// Cost basis and P/L deliberately remain nullable: legacy server positions
/// may not have an average purchase price and the UI must never manufacture
/// one merely to satisfy an older local-only presentation model.
class AuthenticatedPortfolioViewPosition {
  const AuthenticatedPortfolioViewPosition({
    required this.serverPositionId,
    required this.symbol,
    required this.companyName,
    required this.exchange,
    required this.quantity,
    required this.currency,
    required this.currentPrice,
    required this.averagePurchasePrice,
    required this.currentValue,
    required this.investedValue,
    required this.profitLoss,
    required this.profitLossPercentage,
    required this.marketSourceProvider,
    required this.marketObservedAt,
    required this.marketRetrievedAt,
  });

  final int serverPositionId;
  final String symbol;
  final String companyName;
  final String? exchange;
  final double quantity;
  final String? currency;
  final double currentPrice;
  final double? averagePurchasePrice;
  final double currentValue;
  final double? investedValue;
  final double? profitLoss;
  final double? profitLossPercentage;
  final String marketSourceProvider;
  final DateTime marketObservedAt;
  final DateTime marketRetrievedAt;

  factory AuthenticatedPortfolioViewPosition.fromValuedPosition(
    AuthenticatedPortfolioValuedPosition value,
  ) {
    final quote = value.quote;
    final provider = quote.sourceProvider?.trim();
    final retrievedAt = quote.retrievedAt;
    if (provider == null || provider.isEmpty || retrievedAt == null) {
      throw StateError(
        'La posición autenticada no tiene provenance de mercado completa.',
      );
    }
    if (retrievedAt.isBefore(quote.updatedAt)) {
      throw StateError(
        'La recuperación de mercado no puede preceder a la observación.',
      );
    }

    final currency = quote.currency?.trim().toUpperCase();
    return AuthenticatedPortfolioViewPosition(
      serverPositionId: value.holding.id,
      symbol: value.holding.symbol,
      companyName: quote.companyName.trim().isEmpty
          ? value.holding.symbol
          : quote.companyName.trim(),
      exchange: value.holding.exchange ?? quote.exchange?.trim().toUpperCase(),
      quantity: value.holding.quantity,
      currency: currency == null || currency.isEmpty ? null : currency,
      currentPrice: quote.currentPrice,
      averagePurchasePrice: value.holding.averagePurchasePrice,
      currentValue: value.currentValue,
      investedValue: value.investedValue,
      profitLoss: value.profitLoss,
      profitLossPercentage: value.profitLossPercentage,
      marketSourceProvider: provider,
      marketObservedAt: quote.updatedAt,
      marketRetrievedAt: retrievedAt,
    );
  }

  bool get hasCostBasis => averagePurchasePrice != null;

  /// A collection can only be summed directly when every position declares
  /// the same non-empty quote currency. Cross-currency totals must go through
  /// ATHENA's verified FX valuation path instead of silently adding units.
  static String? commonCurrency(
    Iterable<AuthenticatedPortfolioViewPosition> positions,
  ) {
    String? common;
    var seen = false;
    for (final position in positions) {
      seen = true;
      final currency = position.currency;
      if (currency == null || currency.isEmpty) return null;
      if (common == null) {
        common = currency;
      } else if (common != currency) {
        return null;
      }
    }
    return seen ? common : null;
  }
}