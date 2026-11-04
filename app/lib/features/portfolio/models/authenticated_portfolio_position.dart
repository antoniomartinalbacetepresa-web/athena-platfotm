class AuthenticatedPortfolioPosition {
  final int id;
  final String symbol;
  final String? exchange;
  final double quantity;
  final double? averagePurchasePrice;
  final DateTime createdAt;
  final DateTime updatedAt;

  const AuthenticatedPortfolioPosition({
    required this.id,
    required this.symbol,
    required this.exchange,
    required this.quantity,
    this.averagePurchasePrice,
    required this.createdAt,
    required this.updatedAt,
  });

  factory AuthenticatedPortfolioPosition.fromJson(Map<String, dynamic> json) {
    final id = json['id'];
    final symbol = json['symbol'];
    final quantity = json['quantity'];
    final createdAt = DateTime.tryParse(json['createdAt']?.toString() ?? '');
    final updatedAt = DateTime.tryParse(json['updatedAt']?.toString() ?? '');
    if (id is! int || id <= 0) {
      throw const FormatException('Posición autenticada sin id válido.');
    }
    if (symbol is! String || symbol.trim().isEmpty) {
      throw const FormatException('Posición autenticada sin símbolo válido.');
    }
    if (quantity is! num || !quantity.toDouble().isFinite || quantity <= 0) {
      throw const FormatException('Posición autenticada sin cantidad válida.');
    }
    if (createdAt == null || updatedAt == null) {
      throw const FormatException('Posición autenticada sin timestamps válidos.');
    }
    final exchangeRaw = json['exchange'];
    final averagePurchasePriceRaw = json['averagePurchasePrice'];
    double? averagePurchasePrice;
    if (averagePurchasePriceRaw != null) {
      if (averagePurchasePriceRaw is! num) {
        throw const FormatException('Posición autenticada sin precio medio válido.');
      }
      averagePurchasePrice = averagePurchasePriceRaw.toDouble();
      if (!averagePurchasePrice.isFinite ||
          averagePurchasePrice <= 0 ||
          averagePurchasePrice > 1000000000000) {
        throw const FormatException('Posición autenticada sin precio medio válido.');
      }
    }
    return AuthenticatedPortfolioPosition(
      id: id,
      symbol: symbol.trim().toUpperCase(),
      exchange: exchangeRaw is String && exchangeRaw.trim().isNotEmpty
          ? exchangeRaw.trim().toUpperCase()
          : null,
      quantity: quantity.toDouble(),
      averagePurchasePrice: averagePurchasePrice,
      createdAt: createdAt,
      updatedAt: updatedAt,
    );
  }
}