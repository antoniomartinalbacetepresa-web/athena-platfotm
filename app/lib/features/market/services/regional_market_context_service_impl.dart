import '../models/market_region.dart';
import '../models/regional_market_config.dart';
import '../models/regional_market_configs.dart';
import '../models/regional_market_context.dart';
import '../repositories/market_repository.dart';
import 'regional_market_context_service.dart';

/// Implementación del servicio que construye el contexto de una región.
///
/// Obtiene las cotizaciones de los benchmarks configurados y calcula:
/// - activos analizados,
/// - porcentaje de activos que suben,
/// - porcentaje de activos que bajan,
/// - sentimiento regional,
/// - resumen regional.
///
/// IMPORTANTE:
/// Este servicio NO calcula el peso de la región dentro del mercado global.
///
/// Los pesos globales pertenecen a una capa independiente porque deben
/// calcularse utilizando datos reales del universo de mercado.
class RegionalMarketContextServiceImpl
    implements RegionalMarketContextService {
  final MarketRepository marketRepository;

  const RegionalMarketContextServiceImpl({
    required this.marketRepository,
  });

  @override
  Future<RegionalMarketContext> getRegionalContext({
    required MarketRegion region,
  }) async {
    final config = _getConfig(region);

    if (config.benchmarkSymbols.isEmpty) {
      throw StateError(
        'No hay benchmarks configurados para ${config.displayName}.',
      );
    }

    final quotes = await Future.wait(
      config.benchmarkSymbols.map(
        marketRepository.getQuote,
      ),
    );

    if (quotes.isEmpty) {
      throw StateError(
        'No se recibieron cotizaciones para ${config.displayName}.',
      );
    }

    final advancingCount = quotes
        .where(
          (quote) => quote.changePercentage > 0,
        )
        .length;

    final decliningCount = quotes
        .where(
          (quote) => quote.changePercentage < 0,
        )
        .length;

    final totalBenchmarks = quotes.length;

    final advancingPercentage =
        (advancingCount / totalBenchmarks) * 100.0;

    final decliningPercentage =
        (decliningCount / totalBenchmarks) * 100.0;

    final sentiment = _calculateSentiment(
      advancingCount: advancingCount,
      decliningCount: decliningCount,
    );

    return RegionalMarketContext(
      region: config.region.key,
      displayName: config.displayName,
      assetsAnalyzed: totalBenchmarks,
      advancingPercentage: advancingPercentage,
      decliningPercentage: decliningPercentage,
      sentiment: sentiment,
      summary: _buildSummary(
        config: config,
        advancingCount: advancingCount,
        decliningCount: decliningCount,
      ),
      updatedAt: DateTime.now(),
    );
  }

  RegionalMarketConfig _getConfig(MarketRegion region) {
    switch (region) {
      case MarketRegion.america:
        return RegionalMarketConfigs.america;

      case MarketRegion.europe:
        return RegionalMarketConfigs.europe;

      case MarketRegion.asia:
        return RegionalMarketConfigs.asia;
    }
  }

  String _calculateSentiment({
    required int advancingCount,
    required int decliningCount,
  }) {
    if (advancingCount > decliningCount) {
      return 'positive';
    }

    if (decliningCount > advancingCount) {
      return 'negative';
    }

    return 'neutral';
  }

  String _buildSummary({
    required RegionalMarketConfig config,
    required int advancingCount,
    required int decliningCount,
  }) {
    final total = config.benchmarkSymbols.length;

    if (advancingCount > decliningCount) {
      return '${config.displayName}: '
          '$advancingCount de $total benchmarks avanzan.';
    }

    if (decliningCount > advancingCount) {
      return '${config.displayName}: '
          '$decliningCount de $total benchmarks retroceden.';
    }

    return '${config.displayName}: '
        'comportamiento mixto entre los '
        '$total benchmarks de referencia.';
  }
}