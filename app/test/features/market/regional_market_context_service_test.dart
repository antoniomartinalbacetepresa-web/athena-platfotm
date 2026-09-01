import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/models/market_region.dart';
import 'package:app/features/market/repositories/market_repository.dart';
import 'package:app/features/market/services/regional_market_context_service_impl.dart';

class FakeMarketRepository implements MarketRepository {
  final Map<String, MarketQuote> quotes;

  const FakeMarketRepository({
    required this.quotes,
  });

  @override
  Future<MarketQuote> getQuote(String symbol) async {
    final quote = quotes[symbol];

    if (quote == null) {
      throw StateError(
        'No existe una cotización para $symbol.',
      );
    }

    return quote;
  }
}

MarketQuote createQuote({
  required String symbol,
  required double changePercentage,
}) {
  return MarketQuote(
    symbol: symbol,
    companyName: symbol,
    currentPrice: 100,
    change: changePercentage,
    changePercentage: changePercentage,
    updatedAt: DateTime(2026, 8, 24, 12),
  );
}

void main() {
  test(
    'construye correctamente el contexto de América',
    () async {
      final repository = FakeMarketRepository(
        quotes: {
          'SPY': createQuote(
            symbol: 'SPY',
            changePercentage: 1.0,
          ),
          'QQQ': createQuote(
            symbol: 'QQQ',
            changePercentage: 2.0,
          ),
          'DIA': createQuote(
            symbol: 'DIA',
            changePercentage: -0.5,
          ),
        },
      );

      final service = RegionalMarketContextServiceImpl(
        marketRepository: repository,
      );

      final context = await service.getRegionalContext(
        region: MarketRegion.america,
      );

      expect(context.region, 'america');
      expect(context.displayName, 'América');

      expect(context.assetsAnalyzed, 3);

      expect(
        context.advancingPercentage,
        closeTo(66.666666, 0.000001),
      );

      expect(
        context.decliningPercentage,
        closeTo(33.333333, 0.000001),
      );

      expect(context.sentiment, 'positive');

      expect(
        context.summary,
        'América: 2 de 3 benchmarks avanzan.',
      );
    },
  );

  test(
    'construye un contexto negativo cuando predominan '
    'los benchmarks que bajan',
    () async {
      final repository = FakeMarketRepository(
        quotes: {
          'VGK': createQuote(
            symbol: 'VGK',
            changePercentage: -1.0,
          ),
          'FEZ': createQuote(
            symbol: 'FEZ',
            changePercentage: -2.0,
          ),
        },
      );

      final service = RegionalMarketContextServiceImpl(
        marketRepository: repository,
      );

      final context = await service.getRegionalContext(
        region: MarketRegion.europe,
      );

      expect(context.region, 'europe');
      expect(context.displayName, 'Europa');

      expect(context.assetsAnalyzed, 2);
      expect(context.advancingPercentage, 0);
      expect(context.decliningPercentage, 100);

      expect(context.sentiment, 'negative');

      expect(
        context.summary,
        'Europa: 2 de 2 benchmarks retroceden.',
      );
    },
  );

  test(
    'devuelve sentimiento neutral cuando los benchmarks '
    'están equilibrados',
    () async {
      final repository = FakeMarketRepository(
        quotes: {
          'EWJ': createQuote(
            symbol: 'EWJ',
            changePercentage: 1.0,
          ),
          'FXI': createQuote(
            symbol: 'FXI',
            changePercentage: -1.0,
          ),
          'EWH': createQuote(
            symbol: 'EWH',
            changePercentage: 1.0,
          ),
        },
      );

      final service = RegionalMarketContextServiceImpl(
        marketRepository: repository,
      );

      final context = await service.getRegionalContext(
        region: MarketRegion.asia,
      );

      expect(context.region, 'asia');
      expect(context.displayName, 'Asia');

      expect(context.assetsAnalyzed, 3);

      expect(
        context.advancingPercentage,
        closeTo(66.666666, 0.000001),
      );

      expect(
        context.decliningPercentage,
        closeTo(33.333333, 0.000001),
      );

      expect(context.sentiment, 'positive');
    },
  );

  test(
    'considera los benchmarks sin cambio como neutrales',
    () async {
      final repository = FakeMarketRepository(
        quotes: {
          'EWJ': createQuote(
            symbol: 'EWJ',
            changePercentage: 0,
          ),
          'FXI': createQuote(
            symbol: 'FXI',
            changePercentage: 0,
          ),
          'EWH': createQuote(
            symbol: 'EWH',
            changePercentage: 0,
          ),
        },
      );

      final service = RegionalMarketContextServiceImpl(
        marketRepository: repository,
      );

      final context = await service.getRegionalContext(
        region: MarketRegion.asia,
      );

      expect(context.assetsAnalyzed, 3);
      expect(context.advancingPercentage, 0);
      expect(context.decliningPercentage, 0);
      expect(context.sentiment, 'neutral');
    },
  );
}