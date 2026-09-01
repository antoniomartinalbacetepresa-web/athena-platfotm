import '../models/market_universe_asset.dart';
import '../services/fmp_market_universe_data_source.dart';
import 'market_universe_repository.dart';

/// Implementación del repositorio del universo de mercado.
///
/// Delega la obtención de activos en la fuente de datos de FMP.
///
/// Esta capa no contiene lógica de inversión ni recomendaciones.
class MarketUniverseRepositoryImpl
    implements MarketUniverseRepository {
  final FmpMarketUniverseDataSource dataSource;

  const MarketUniverseRepositoryImpl({
    required this.dataSource,
  });

  @override
  Future<List<MarketUniverseAsset>> getUniverse() {
    return dataSource.getUniverse();
  }
}