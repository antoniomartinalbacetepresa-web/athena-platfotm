import '../models/market_universe_asset.dart';

/// Repositorio encargado de proporcionar el universo de activos.
///
/// La capa superior no necesita conocer cómo ni de dónde
/// se obtienen los activos.
abstract interface class MarketUniverseRepository {
  /// Obtiene el universo de activos disponible.
  Future<List<MarketUniverseAsset>> getUniverse();
}