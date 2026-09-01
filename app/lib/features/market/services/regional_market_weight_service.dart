import '../models/market_region.dart';
import '../models/market_universe_asset.dart';
import '../models/regional_market_weights.dart';

/// Calcula el peso de cada región a partir de la capitalización
/// de mercado del universo analizado.
///
/// Este servicio no realiza llamadas externas y no contiene
/// lógica de inversión o recomendaciones.
class RegionalMarketWeightService {
  const RegionalMarketWeightService();

  RegionalMarketWeights calculate(List<MarketUniverseAsset> assets) {
    double americaMarketCap = 0;
    double europeMarketCap = 0;
    double asiaMarketCap = 0;

    for (final asset in assets) {
      if (!asset.isValid || !asset.hasMarketCap) {
        continue;
      }

      final region = _regionForAsset(asset);

      if (region == null) {
        continue;
      }

      final marketCap = asset.marketCap!;

      switch (region) {
        case MarketRegion.america:
          americaMarketCap += marketCap;
          break;

        case MarketRegion.europe:
          europeMarketCap += marketCap;
          break;

        case MarketRegion.asia:
          asiaMarketCap += marketCap;
          break;
      }
    }

    final totalMarketCap = americaMarketCap + europeMarketCap + asiaMarketCap;

    if (totalMarketCap <= 0) {
      throw StateError(
        'No existe capitalización de mercado válida '
        'para calcular los pesos regionales.',
      );
    }

    return RegionalMarketWeights(
      america: americaMarketCap / totalMarketCap,
      europe: europeMarketCap / totalMarketCap,
      asia: asiaMarketCap / totalMarketCap,
    );
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
