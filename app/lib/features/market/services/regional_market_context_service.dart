import '../models/market_region.dart';
import '../models/regional_market_context.dart';

/// Construye el contexto agregado de una región.
///
/// Este servicio define el contrato que debe cumplir cualquier
/// implementación encargada de construir el contexto regional.
///
/// No contiene lógica de inversión ni genera recomendaciones.
abstract interface class RegionalMarketContextService {
  /// Obtiene el contexto actual de una región.
  Future<RegionalMarketContext> getRegionalContext({
    required MarketRegion region,
  });
}