import '../models/market_context.dart';
import 'market_context_service.dart';

/// Servicio fail-closed para el contrato legado [MarketContext].
///
/// La aplicación productiva utiliza [GlobalMarketDataService] para construir
/// el contexto global con datos reales y provenance explícita. Este contrato
/// legado no puede representar esa provenance ni el estado de readiness del
/// universo, por lo que adaptarlo silenciosamente degradaría la semántica.
///
/// Se mantiene únicamente para compatibilidad estructural y falla de forma
/// explícita si algún consumidor intenta utilizarlo en configuración real.
class UnavailableMarketContextService implements MarketContextService {
  const UnavailableMarketContextService();

  @override
  Future<MarketContext> getMarketContext() {
    return Future<MarketContext>.error(
      StateError(
        'El contexto de mercado legado no está disponible en modo real. '
        'Utilice GlobalMarketDataService para contexto global verificable.',
      ),
    );
  }
}
