import '../data/athena_backend_portfolio_correlation_data_source.dart';
import '../data/athena_backend_portfolio_identity_data_source.dart';
import '../models/authenticated_portfolio_view_position.dart';
import '../models/portfolio_correlation_snapshot.dart';
import '../models/portfolio_position.dart';
import 'portfolio_correlation_evidence_service.dart';
import 'portfolio_identity_enrichment_service.dart';

/// Read-only bridge from JWT-owner-scoped holdings to canonical PIT correlation.
///
/// Never consumes the guest/local portfolio, guesses an instrument ID from a
/// ticker, or promotes correlation into advice, weighting or trading.
class AuthenticatedPortfolioCorrelationService {
  const AuthenticatedPortfolioCorrelationService({
    required this.resolveIdentity,
    required this.loadPair,
    this._disposeDependencies,
  });

  final PortfolioIdentityResolver resolveIdentity;
  final PortfolioPairCorrelationLoader loadPair;
  final void Function()? _disposeDependencies;

  factory AuthenticatedPortfolioCorrelationService.forBackend({
    required String backendUrl,
  }) {
    final url = backendUrl.replaceAll(RegExp(r'/+$'), '');
    final identity = AthenaBackendPortfolioIdentityDataSource(baseUrl: url);
    final correlation = AthenaBackendPortfolioCorrelationDataSource(baseUrl: url);
    return AuthenticatedPortfolioCorrelationService(
      resolveIdentity: identity.resolve,
      loadPair: correlation.getPair,
      _disposeDependencies: () {
        identity.dispose();
        correlation.dispose();
      },
    );
  }

  Future<PortfolioCorrelationSnapshot> analyze({
    required List<AuthenticatedPortfolioViewPosition> positions,
  }) async {
    if (positions.length < 2) {
      throw StateError('Se necesitan al menos dos posiciones autenticadas.');
    }
    final enriched = <PortfolioPosition>[];
    const identityService = PortfolioIdentityEnrichmentService();
    for (final holding in positions) {
      final observedAt = holding.marketObservedAt.toUtc();
      final retrievedAt = holding.marketRetrievedAt.toUtc();
      if (retrievedAt.isBefore(observedAt) ||
          observedAt.isAfter(DateTime.now().toUtc()) ||
          retrievedAt.isAfter(DateTime.now().toUtc())) {
        throw StateError('Cotización sin provenance temporal válida.');
      }
      // averagePrice is a non-financial sentinel for this transient
      // correlation-only adapter, NEVER a fabricated acquisition cost.
      // The correlation engine reads identity and market provenance only.
      final transient = PortfolioPosition(
        symbol: holding.symbol,
        companyName: holding.companyName,
        shares: holding.quantity,
        averagePrice: holding.averagePurchasePrice ?? 0,
        currentPrice: holding.currentPrice,
        exchange: holding.exchange,
        priceCurrency: holding.currency,
        currentPriceUpdatedAt: observedAt,
        currentPriceRetrievedAt: retrievedAt,
        currentPriceSourceProvider: holding.marketSourceProvider,
      );
      enriched.add(await identityService.enrich(
        position: transient,
        resolver: resolveIdentity,
      ));
    }
    // Cutoff is fixed AFTER canonical identity resolution, BEFORE any pair
    // query. Future-dated identity evidence cannot enter this PIT snapshot.
    final cutoff = DateTime.now().toUtc();
    for (final position in enriched) {
      if (position.identityRetrievedAt!.isAfter(cutoff) ||
          position.currentPriceRetrievedAt!.isAfter(cutoff)) {
        throw StateError('Identidad o mercado posteriores al knowledgeCutoff.');
      }
    }
    // Multiple lots of the same verified instrument are one exposure for
    // pairwise correlation. Conflicting provider/identity is never merged.
    final byInstrument = <int, PortfolioPosition>{};
    for (final position in enriched) {
      final id = position.databaseInstrumentId!;
      final previous = byInstrument[id];
      if (previous != null) {
        if (previous.canonicalInstrumentId != position.canonicalInstrumentId ||
            previous.canonicalIssuerId != position.canonicalIssuerId ||
            previous.currentPriceSourceProvider !=
                position.currentPriceSourceProvider ||
            previous.priceCurrency != position.priceCurrency) {
          throw StateError('Lotes con identidad canónica contradictoria.');
        }
      } else {
        byInstrument[id] = position;
      }
    }
    return PortfolioCorrelationEvidenceService(loadPair: loadPair).analyze(
      positions: List.unmodifiable(byInstrument.values),
      knowledgeCutoff: cutoff,
    );
  }

  void dispose() => _disposeDependencies?.call();
}
