import '../../market/models/fx_quote.dart';
import '../models/authenticated_portfolio_view_position.dart';

typedef AuthenticatedPortfolioFxLoader = Future<FxQuote> Function({
  required String baseCurrency,
  required String quoteCurrency,
});

class AuthenticatedPortfolioFxValuation {
  const AuthenticatedPortfolioFxValuation({
    required this.baseCurrency,
    required this.currentValueInBaseCurrency,
    required this.positionsValued,
    required this.fxEvidence,
    required this.latestMarketObservedAt,
    required this.latestMarketRetrievedAt,
    required this.latestFxObservedAt,
    required this.latestFxRetrievedAt,
  });

  final String baseCurrency;
  final double currentValueInBaseCurrency;
  final int positionsValued;
  final List<FxQuote> fxEvidence;
  final DateTime latestMarketObservedAt;
  final DateTime latestMarketRetrievedAt;
  final DateTime? latestFxObservedAt;
  final DateTime? latestFxRetrievedAt;

  bool get usesFx => fxEvidence.isNotEmpty;
}

/// Values authenticated owner holdings in one declared base currency without
/// converting them into the legacy local PortfolioPosition model.
///
/// Holdings/cost basis remain server-authoritative. Market prices already carry
/// provenance in [AuthenticatedPortfolioViewPosition]; cross-currency current
/// value is accepted only through validated ATHENA FX evidence. Historical cost
/// basis is intentionally not converted here because authenticated holdings do
/// not yet persist a verified economic acquisition date. P/L must therefore
/// remain unavailable cross-currency rather than using today's FX rate.
class AuthenticatedPortfolioFxValuationService {
  const AuthenticatedPortfolioFxValuationService({
    required this.loadCurrentFxRate,
  });

  final AuthenticatedPortfolioFxLoader loadCurrentFxRate;

  Future<AuthenticatedPortfolioFxValuation> value({
    required List<AuthenticatedPortfolioViewPosition> positions,
    required String baseCurrency,
  }) async {
    if (positions.isEmpty) {
      throw StateError('No hay posiciones autenticadas que valorar.');
    }
    final base = _currency(baseCurrency, 'baseCurrency');
    final fxByCurrency = <String, FxQuote>{};
    final fxEvidence = <FxQuote>[];
    var total = 0.0;
    DateTime? latestMarketObserved;
    DateTime? latestMarketRetrieved;
    DateTime? latestFxObserved;
    DateTime? latestFxRetrieved;

    for (final position in positions) {
      if (!position.currentValue.isFinite || position.currentValue < 0) {
        throw StateError('Valor actual inválido para ${position.symbol}.');
      }
      if (position.marketRetrievedAt.isBefore(position.marketObservedAt)) {
        throw StateError('Provenance temporal inválida para ${position.symbol}.');
      }
      final source = _currency(
        position.currency ?? '',
        'currency(${position.symbol})',
      );
      latestMarketObserved = _latest(latestMarketObserved, position.marketObservedAt);
      latestMarketRetrieved = _latest(latestMarketRetrieved, position.marketRetrievedAt);

      if (source == base) {
        total += position.currentValue;
        continue;
      }

      var fx = fxByCurrency[source];
      if (fx == null) {
        fx = await loadCurrentFxRate(baseCurrency: source, quoteCurrency: base);
        _validateFx(fx, expectedBase: source, expectedQuote: base);
        fxByCurrency[source] = fx;
        fxEvidence.add(fx);
      }
      final converted = fx.convertCurrent(position.currentValue);
      if (!converted.isFinite || converted < 0) {
        throw StateError('Conversión FX inválida para ${position.symbol}.');
      }
      total += converted;
      latestFxObserved = _latest(latestFxObserved, fx.observedAt);
      latestFxRetrieved = _latest(latestFxRetrieved, fx.retrievedAt);
    }

    if (!total.isFinite || total < 0 ||
        latestMarketObserved == null || latestMarketRetrieved == null) {
      throw StateError('Valoración autenticada no verificable.');
    }

    return AuthenticatedPortfolioFxValuation(
      baseCurrency: base,
      currentValueInBaseCurrency: total,
      positionsValued: positions.length,
      fxEvidence: List.unmodifiable(fxEvidence),
      latestMarketObservedAt: latestMarketObserved,
      latestMarketRetrievedAt: latestMarketRetrieved,
      latestFxObservedAt: latestFxObserved,
      latestFxRetrievedAt: latestFxRetrieved,
    );
  }

  static void _validateFx(
    FxQuote fx, {
    required String expectedBase,
    required String expectedQuote,
  }) {
    if (fx.baseCurrency != expectedBase || fx.quoteCurrency != expectedQuote) {
      throw StateError('La evidencia FX no corresponde al par solicitado.');
    }
    if (fx.status.trim().toLowerCase() != 'ok') {
      throw StateError('La evidencia FX no está disponible.');
    }
    if (fx.historicalPointInTimeEligible) {
      throw StateError('La cotización FX actual no puede declararse PIT histórica.');
    }
    if (fx.sourceProvider.trim().isEmpty || fx.retrievedAt.isBefore(fx.observedAt)) {
      throw StateError('La evidencia FX no tiene provenance válida.');
    }
  }

  static String _currency(String value, String field) {
    final normalized = value.trim().toUpperCase();
    if (!RegExp(r'^[A-Z]{3}$').hasMatch(normalized)) {
      throw StateError('$field no contiene una moneda ISO verificable.');
    }
    return normalized;
  }

  static DateTime _latest(DateTime? current, DateTime candidate) {
    if (current == null || candidate.isAfter(current)) return candidate;
    return current;
  }
}
