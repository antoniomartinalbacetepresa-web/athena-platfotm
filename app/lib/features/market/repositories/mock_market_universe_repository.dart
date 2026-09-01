import '../models/market_universe_asset.dart';
import 'market_universe_repository.dart';

/// Repositorio simulado del universo de mercado.
///
/// Se utiliza cuando ATHENA TYCHE no dispone de una API key.
/// No realiza ninguna comunicación externa.
class MockMarketUniverseRepository
    implements MarketUniverseRepository {
  const MockMarketUniverseRepository();

  @override
  Future<List<MarketUniverseAsset>> getUniverse() async {
    return const [
      MarketUniverseAsset(
        symbol: 'AAPL',
        companyName: 'Apple Inc.',
        marketCap: 0,
        country: 'United States',
        exchange: 'NASDAQ',
        exchangeShortName: 'NASDAQ',
        sector: 'Technology',
        industry: 'Consumer Electronics',
      ),
      MarketUniverseAsset(
        symbol: 'MSFT',
        companyName: 'Microsoft Corporation',
        marketCap: 0,
        country: 'United States',
        exchange: 'NASDAQ',
        exchangeShortName: 'NASDAQ',
        sector: 'Technology',
        industry: 'Software - Infrastructure',
      ),
      MarketUniverseAsset(
        symbol: 'NVDA',
        companyName: 'NVIDIA Corporation',
        marketCap: 0,
        country: 'United States',
        exchange: 'NASDAQ',
        exchangeShortName: 'NASDAQ',
        sector: 'Technology',
        industry: 'Semiconductors',
      ),
    ];
  }
}
