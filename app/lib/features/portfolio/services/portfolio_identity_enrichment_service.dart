import '../models/portfolio_instrument_identity.dart';
import '../models/portfolio_position.dart';

typedef PortfolioIdentityResolver = Future<PortfolioInstrumentIdentity> Function({
  required String symbol,
  String? exchange,
});

/// Enriches a persisted portfolio position with canonical backend identity.
///
/// The operation is deliberately fail-closed: a position is not made eligible
/// for correlation/risk merely because a ticker exists. Symbol, listing and
/// currency must all agree with the verified backend identity.
class PortfolioIdentityEnrichmentService {
  const PortfolioIdentityEnrichmentService();

  Future<PortfolioPosition> enrich({
    required PortfolioPosition position,
    required PortfolioIdentityResolver resolver,
  }) async {
    final symbol = position.symbol.trim().toUpperCase();
    final exchange = position.exchange?.trim().toUpperCase();
    final currency = position.priceCurrency?.trim().toUpperCase();

    if (symbol.isEmpty) {
      throw StateError('No se puede resolver identidad con símbolo vacío.');
    }
    if (exchange == null || exchange.isEmpty) {
      throw StateError(
        'La identidad de cartera requiere exchange verificable antes de riesgo.',
      );
    }
    if (currency == null || !RegExp(r'^[A-Z]{3}$').hasMatch(currency)) {
      throw StateError(
        'La identidad de cartera requiere moneda ISO verificable del instrumento.',
      );
    }

    final identity = await resolver(symbol: symbol, exchange: exchange);

    if (identity.symbol != symbol) {
      throw StateError('La identidad canónica pertenece a otro símbolo.');
    }
    final exchangeMatches = identity.exchange == exchange ||
        identity.exchangeShortName == exchange;
    if (!exchangeMatches || !identity.exchangeVerified) {
      throw StateError('La identidad canónica no verifica el listing solicitado.');
    }
    if (identity.currency != currency) {
      throw StateError(
        'La moneda de la identidad canónica no coincide con la cotización.',
      );
    }
    if (!identity.isRiskReady) {
      throw StateError(
        'La identidad resuelta es diagnóstica y no es apta para riesgo.',
      );
    }
    if (identity.databaseInstrumentId <= 0 ||
        identity.canonicalInstrumentId.trim().isEmpty ||
        identity.issuerId.trim().isEmpty ||
        identity.sourceProvider.trim().isEmpty ||
        identity.resolutionMethod.trim().isEmpty) {
      throw StateError('La identidad canónica carece de provenance suficiente.');
    }
    if (identity.recommendationPolicy != 'no_advice' ||
        identity.productionEligible ||
        identity.automaticTrading) {
      throw StateError(
        'La identidad no puede elevar advice, producción ni trading.',
      );
    }

    return position.copyWith(
      symbol: symbol,
      exchange: exchange,
      priceCurrency: currency,
      databaseInstrumentId: identity.databaseInstrumentId,
      canonicalInstrumentId: identity.canonicalInstrumentId,
      canonicalIssuerId: identity.issuerId,
      identitySourceProvider: identity.sourceProvider,
      identityRetrievedAt: identity.retrievedAt.toUtc(),
      identityResolutionMethod: identity.resolutionMethod,
      identityExchangeVerified: identity.exchangeVerified,
      identityRiskReady: identity.isRiskReady,
    );
  }
}
