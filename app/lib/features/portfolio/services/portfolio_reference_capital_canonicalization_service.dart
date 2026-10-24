import '../../market/models/fx_quote.dart';

typedef PortfolioReferenceCapitalFxLoader = Future<FxQuote> Function({
  required String baseCurrency,
  required String quoteCurrency,
});

class PortfolioCanonicalReferenceCapital {
  static const canonicalCurrency = 'USD';
  static const preferredDisplayCurrency = 'EUR';

  final double originalAmount;
  final String originalCurrency;
  final double amountInCanonicalCurrency;
  final FxQuote? fxEvidence;

  const PortfolioCanonicalReferenceCapital({
    required this.originalAmount,
    required this.originalCurrency,
    required this.amountInCanonicalCurrency,
    required this.fxEvidence,
  });

  bool get usedFx => fxEvidence != null;
}

/// Normalizes the user's declared reference capital into ATHENA's single
/// calculation currency (USD) without reinterpreting the original amount.
///
/// The original amount/currency remain authoritative user input. Cross-currency
/// normalization is allowed only through a verified current FX quote returned
/// by the ATHENA backend. Missing or inconsistent FX fails closed.
class PortfolioReferenceCapitalCanonicalizationService {
  final PortfolioReferenceCapitalFxLoader loadCurrentFxRate;

  const PortfolioReferenceCapitalCanonicalizationService({
    required this.loadCurrentFxRate,
  });

  Future<PortfolioCanonicalReferenceCapital> canonicalize({
    required double amount,
    required String currency,
  }) async {
    if (!amount.isFinite || amount < 0) {
      throw ArgumentError.value(
        amount,
        'amount',
        'El capital de referencia debe ser finito y no negativo.',
      );
    }

    final sourceCurrency = _normalizeCurrency(currency);
    if (sourceCurrency == PortfolioCanonicalReferenceCapital.canonicalCurrency) {
      return PortfolioCanonicalReferenceCapital(
        originalAmount: amount,
        originalCurrency: sourceCurrency,
        amountInCanonicalCurrency: amount,
        fxEvidence: null,
      );
    }

    final fx = await loadCurrentFxRate(
      baseCurrency: sourceCurrency,
      quoteCurrency: PortfolioCanonicalReferenceCapital.canonicalCurrency,
    );
    _validateFx(fx, expectedBase: sourceCurrency);

    final canonicalAmount = fx.convertCurrent(amount);
    if (!canonicalAmount.isFinite || canonicalAmount < 0) {
      throw StateError(
        'La conversión FX produjo un capital canónico inválido.',
      );
    }

    return PortfolioCanonicalReferenceCapital(
      originalAmount: amount,
      originalCurrency: sourceCurrency,
      amountInCanonicalCurrency: canonicalAmount,
      fxEvidence: fx,
    );
  }

  String _normalizeCurrency(String value) {
    final normalized = value.trim().toUpperCase();
    if (!RegExp(r'^[A-Z]{3}$').hasMatch(normalized)) {
      throw ArgumentError.value(
        value,
        'currency',
        'La moneda del capital debe ser ISO de tres letras.',
      );
    }
    return normalized;
  }

  void _validateFx(FxQuote fx, {required String expectedBase}) {
    if (fx.baseCurrency != expectedBase ||
        fx.quoteCurrency != PortfolioCanonicalReferenceCapital.canonicalCurrency) {
      throw StateError(
        'La evidencia FX no corresponde a la normalización monetaria solicitada.',
      );
    }
    if (!fx.rate.isFinite || fx.rate <= 0) {
      throw StateError('La evidencia FX contiene una tasa inválida.');
    }
    if (fx.sourceProvider.trim().isEmpty) {
      throw StateError('La evidencia FX no declara proveedor.');
    }
    final sourceSymbol = fx.sourceSymbol?.trim().toUpperCase();
    final expectedSymbol =
        '$expectedBase${PortfolioCanonicalReferenceCapital.canonicalCurrency}=X';
    if (sourceSymbol != expectedSymbol) {
      throw StateError('La evidencia FX no declara el par fuente esperado.');
    }
    if (fx.retrievedAt.isBefore(fx.observedAt)) {
      throw StateError('La recuperación FX precede a su observación.');
    }
    if (fx.historicalPointInTimeEligible) {
      throw StateError(
        'La normalización actual no acepta evidencia declarada como PIT histórica.',
      );
    }
  }
}
