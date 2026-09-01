import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/data/models/market_data_point.dart';
import 'package:app/features/market/data/providers/market_data_provider.dart';
import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/services/twelve_data_market_service.dart';

class FakeMarketDataProvider implements MarketDataProvider {
  final MarketDataPoint? quote;

  const FakeMarketDataProvider({
    required this.quote,
  });

  @override
  String get providerId => 'twelve_data';

  @override
  Future<MarketDataPoint?> getQuote(String symbol) async {
    return quote;
  }

  @override
  Future<List<MarketDataPoint>> getHistoricalData({
    required String symbol,
    DateTime? from,
    DateTime? to,
  }) async {
    return const [];
  }
}

MarketDataPoint createDataPoint({
  double? close = 229.75,
  double? change = 2.15,
  double? changePercentage = 0.96,
}) {
  return MarketDataPoint(
    symbol: 'AAPL',
    timestamp: DateTime(2026, 8, 28, 15, 30),
    close: close,
    change: change,
    changePercentage: changePercentage,
    providerId: 'twelve_data',
  );
}

void main() {
  test(
    'convierte correctamente MarketDataPoint en MarketQuote',
    () async {
      final provider = FakeMarketDataProvider(
        quote: createDataPoint(),
      );

      final service = TwelveDataMarketService(
        provider: provider,
      );

      final result = await service.getQuote('aapl');

      expect(result, isA<MarketQuote>());
      expect(result.symbol, 'AAPL');
      expect(result.companyName, 'AAPL');
      expect(result.currentPrice, 229.75);
      expect(result.change, 2.15);
      expect(result.changePercentage, 0.96);
      expect(result.marketCap, isNull);
      expect(
        result.updatedAt,
        DateTime(2026, 8, 28, 15, 30),
      );
    },
  );

  test(
    'calcula el cambio absoluto cuando el proveedor '
    'no lo proporciona',
    () async {
      final provider = FakeMarketDataProvider(
        quote: createDataPoint(
          close: 200,
          change: null,
          changePercentage: 5,
        ),
      );

      final service = TwelveDataMarketService(
        provider: provider,
      );

      final result = await service.getQuote('AAPL');

      expect(result.currentPrice, 200);
      expect(result.changePercentage, 5);
      expect(result.change, 10);
    },
  );

  test(
    'rechaza un símbolo vacío',
    () async {
      final provider = FakeMarketDataProvider(
        quote: createDataPoint(),
      );

      final service = TwelveDataMarketService(
        provider: provider,
      );

      expect(
        () => service.getQuote('   '),
        throwsArgumentError,
      );
    },
  );

  test(
    'rechaza una cotización inexistente',
    () async {
      final provider = FakeMarketDataProvider(
        quote: null,
      );

      final service = TwelveDataMarketService(
        provider: provider,
      );

      expect(
        service.getQuote('AAPL'),
        throwsFormatException,
      );
    },
  );

  test(
    'rechaza una cotización sin precio',
    () async {
      final provider = FakeMarketDataProvider(
        quote: createDataPoint(
          close: null,
        ),
      );

      final service = TwelveDataMarketService(
        provider: provider,
      );

      expect(
        service.getQuote('AAPL'),
        throwsFormatException,
      );
    },
  );

  test(
    'rechaza una cotización sin cambio porcentual',
    () async {
      final provider = FakeMarketDataProvider(
        quote: createDataPoint(
          changePercentage: null,
        ),
      );

      final service = TwelveDataMarketService(
        provider: provider,
      );

      expect(
        service.getQuote('AAPL'),
        throwsFormatException,
      );
    },
  );
}