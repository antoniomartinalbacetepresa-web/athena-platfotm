import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/repositories/market_repository.dart';
import 'package:app/features/market/repositories/market_repository_impl.dart';
import 'package:app/features/market/services/market_service.dart';

class FakeMarketService implements MarketService {
  @override
  Future<MarketQuote> getQuote(String symbol) async {
    return MarketQuote(
      symbol: symbol.trim().toUpperCase(),
      companyName: 'Apple Inc.',
      currentPrice: 305.93,
      change: 0.67,
      changePercentage: 0.21949,
      updatedAt: DateTime.utc(2026, 1, 1),
    );
  }
}

void main() {
  test(
    'MarketRepositoryImpl devuelve la cotización proporcionada por MarketService',
    () async {
      final MarketRepository repository =
          MarketRepositoryImpl(
        marketService: FakeMarketService(),
      );

      final result = await repository.getQuote('aapl');

      expect(result.symbol, 'AAPL');
      expect(result.companyName, 'Apple Inc.');
      expect(result.currentPrice, 305.93);
      expect(result.change, 0.67);
      expect(result.changePercentage, 0.21949);
    },
  );
}