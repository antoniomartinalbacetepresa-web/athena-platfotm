import '../data/datasources/athena_backend_market_universe_data_source.dart';
import '../models/market_universe_asset.dart';
import 'market_universe_repository.dart';

/// Implementación del repositorio del universo de mercado.
///
/// Delega la obtención de activos en el backend de ATHENA TYCHE.
/// Flutter no conoce ni depende de proveedores externos concretos.
class MarketUniverseRepositoryImpl implements MarketUniverseRepository {
  final AthenaBackendMarketUniverseDataSource dataSource;

  const MarketUniverseRepositoryImpl({
    required this.dataSource,
  });

  @override
  Future<List<MarketUniverseAsset>> getUniverse() {
    return dataSource.getUniverse();
  }
}
