import 'dart:math' as math;

import '../models/market_region.dart';
import '../models/market_universe_asset.dart';
import '../models/regional_market_weights.dart';

/// Calcula el peso de cada región a partir de la capitalización
/// de mercado del universo analizado.
///
/// Además calcula una confianza conservadora basada en:
/// - cobertura útil del universo;
/// - presencia de las tres regiones;
/// - tamaño de la muestra válida.
///
/// Este servicio no realiza llamadas externas y no contiene
/// lógica de inversión o recomendaciones.
class RegionalMarketWeightService {
  const RegionalMarketWeightService();

  RegionalMarketWeights calculate(List<MarketUniverseAsset> assets) {
    double americaMarketCap = 0;
    double europeMarketCap = 0;
    double asiaMarketCap = 0;

    var validAssets = 0;
    var americaAssets = 0;
    var europeAssets = 0;
    var asiaAssets = 0;

    for (final asset in assets) {
      if (!asset.isValid || !asset.hasMarketCap) {
        continue;
      }

      final region = _regionForAsset(asset);

      if (region == null) {
        continue;
      }

      validAssets += 1;
      final marketCap = asset.marketCap!;

      switch (region) {
        case MarketRegion.america:
          americaMarketCap += marketCap;
          americaAssets += 1;
          break;

        case MarketRegion.europe:
          europeMarketCap += marketCap;
          europeAssets += 1;
          break;

        case MarketRegion.asia:
          asiaMarketCap += marketCap;
          asiaAssets += 1;
          break;
      }
    }

    final totalMarketCap = americaMarketCap + europeMarketCap + asiaMarketCap;

    if (totalMarketCap <= 0 || validAssets == 0) {
      throw StateError(
        'No existe capitalización de mercado válida '
        'para calcular los pesos regionales.',
      );
    }

    final confidence = _calculateConfidence(
      totalAssets: assets.length,
      validAssets: validAssets,
      americaAssets: americaAssets,
      europeAssets: europeAssets,
      asiaAssets: asiaAssets,
    );

    return RegionalMarketWeights(
      america: americaMarketCap / totalMarketCap,
      europe: europeMarketCap / totalMarketCap,
      asia: asiaMarketCap / totalMarketCap,
      confidence: confidence,
    );
  }

  double _calculateConfidence({
    required int totalAssets,
    required int validAssets,
    required int americaAssets,
    required int europeAssets,
    required int asiaAssets,
  }) {
    if (totalAssets <= 0 || validAssets <= 0) {
      return 0;
    }

    final coverageScore = validAssets / totalAssets;

    final representedRegions = [
      americaAssets,
      europeAssets,
      asiaAssets,
    ].where((count) => count > 0).length;

    final regionalScore = representedRegions / 3.0;

    // 300 observaciones válidas se consideran una primera referencia
    // para alcanzar la puntuación máxima por tamaño. Esta referencia no
    // afirma que 300 activos constituyan un universo mundial completo:
    // únicamente evita asignar confianza total a muestras muy pequeñas.
    final sampleSizeScore = math.min(validAssets / 300.0, 1.0);

    // La cobertura tiene el mayor peso, seguida de la representación de
    // regiones. El tamaño de muestra penaliza de forma explícita universos
    // piloto aunque sus pocos elementos estén completamente informados.
    final confidence =
        (coverageScore * 0.45) +
        (regionalScore * 0.25) +
        (sampleSizeScore * 0.30);

    return confidence.clamp(0.0, 1.0).toDouble();
  }

  MarketRegion? _regionForAsset(MarketUniverseAsset asset) {
    final country = asset.country?.trim().toLowerCase();

    if (country == null || country.isEmpty) {
      return null;
    }

    if (_americaCountries.contains(country)) {
      return MarketRegion.america;
    }

    if (_europeCountries.contains(country)) {
      return MarketRegion.europe;
    }

    if (_asiaCountries.contains(country)) {
      return MarketRegion.asia;
    }

    return null;
  }

  static const Set<String> _americaCountries = {
    'united states',
    'united states of america',
    'usa',
    'us',
    'canada',
    'mexico',
    'brazil',
    'argentina',
    'chile',
    'colombia',
    'peru',
    'uruguay',
    'panama',
    'costa rica',
    'bermuda',
  };

  static const Set<String> _europeCountries = {
    'united kingdom',
    'uk',
    'great britain',
    'germany',
    'france',
    'italy',
    'spain',
    'netherlands',
    'belgium',
    'switzerland',
    'austria',
    'sweden',
    'norway',
    'denmark',
    'finland',
    'ireland',
    'portugal',
    'poland',
    'greece',
    'czech republic',
    'czechia',
    'hungary',
    'romania',
    'iceland',
    'luxembourg',
  };

  static const Set<String> _asiaCountries = {
    'china',
    'hong kong',
    'japan',
    'india',
    'south korea',
    'korea',
    'taiwan',
    'singapore',
    'indonesia',
    'malaysia',
    'thailand',
    'vietnam',
    'philippines',
  };
}
