import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/models/market_region.dart';
import 'package:app/features/market/models/regional_market_configs.dart';

void main() {
  test(
    'RegionalMarketConfigs contiene las tres regiones principales',
    () {
      expect(
        RegionalMarketConfigs.all.length,
        3,
      );

      expect(
        RegionalMarketConfigs.all.map((config) => config.region),
        containsAll([
          MarketRegion.america,
          MarketRegion.europe,
          MarketRegion.asia,
        ]),
      );
    },
  );

  test(
    'Cada región tiene benchmarks configurados',
    () {
      for (final config in RegionalMarketConfigs.all) {
        expect(
          config.benchmarkSymbols,
          isNotEmpty,
        );
      }
    },
  );

  test(
    'Los benchmarks contienen símbolos de mercado válidos',
    () {
      for (final config in RegionalMarketConfigs.all) {
        for (final symbol in config.benchmarkSymbols) {
          expect(symbol, isNotEmpty);
          expect(symbol.trim(), symbol);
        }
      }
    },
  );

  test(
    'No existen símbolos benchmark duplicados entre regiones',
    () {
      final symbols = RegionalMarketConfigs.all
          .expand((config) => config.benchmarkSymbols)
          .toList();

      expect(
        symbols.toSet().length,
        symbols.length,
      );
    },
  );
}