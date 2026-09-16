import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/models/fx_quote.dart';
import 'package:app/features/portfolio/services/portfolio_reference_capital_canonicalization_service.dart';

FxQuote fx({
  required String base,
  required String quote,
  required double rate,
  DateTime? observedAt,
  DateTime? retrievedAt,
}) {
  final observed = observedAt ?? DateTime.utc(2026, 9, 6, 12);
  return FxQuote(
    status: 'ok',
    baseCurrency: base,
    quoteCurrency: quote,
    rate: rate,
    observedAt: observed,
    retrievedAt: retrievedAt ?? observed.add(const Duration(seconds: 1)),
    sourceProvider: 'yahoo',
    sourceSymbol: '$base$quote=X',
    historicalPointInTimeEligible: false,
  );
}

void main() {
  test('keeps USD reference capital unchanged without requesting FX', () async {
    var calls = 0;
    final service = PortfolioReferenceCapitalCanonicalizationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        calls += 1;
        throw StateError('FX must not be requested for USD capital');
      },
    );

    final result = await service.canonicalize(
      amount: 10000,
      currency: ' usd ',
    );

    expect(calls, 0);
    expect(result.originalAmount, 10000);
    expect(result.originalCurrency, 'USD');
    expect(result.amountInCanonicalCurrency, 10000);
    expect(result.fxEvidence, isNull);
    expect(result.usedFx, isFalse);
    expect(PortfolioCanonicalReferenceCapital.canonicalCurrency, 'USD');
    expect(PortfolioCanonicalReferenceCapital.preferredDisplayCurrency, 'EUR');
  });

  test('converts EUR reference capital to USD only with verified backend FX', () async {
    final service = PortfolioReferenceCapitalCanonicalizationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        expect(baseCurrency, 'EUR');
        expect(quoteCurrency, 'USD');
        return fx(base: 'EUR', quote: 'USD', rate: 1.10);
      },
    );

    final result = await service.canonicalize(
      amount: 10000,
      currency: 'EUR',
    );

    expect(result.originalAmount, 10000);
    expect(result.originalCurrency, 'EUR');
    expect(result.amountInCanonicalCurrency, closeTo(11000, 1e-9));
    expect(result.fxEvidence?.baseCurrency, 'EUR');
    expect(result.fxEvidence?.quoteCurrency, 'USD');
    expect(result.fxEvidence?.sourceProvider, 'yahoo');
    expect(result.usedFx, isTrue);
  });

  test('fails closed when backend returns FX for another pair', () async {
    final service = PortfolioReferenceCapitalCanonicalizationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        return fx(base: 'GBP', quote: 'USD', rate: 1.30);
      },
    );

    expect(
      () => service.canonicalize(amount: 10000, currency: 'EUR'),
      throwsStateError,
    );
  });

  test('rejects nonfinite or negative capital before any FX request', () async {
    var calls = 0;
    final service = PortfolioReferenceCapitalCanonicalizationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        calls += 1;
        return fx(base: baseCurrency, quote: quoteCurrency, rate: 1);
      },
    );

    await expectLater(
      service.canonicalize(amount: double.nan, currency: 'EUR'),
      throwsArgumentError,
    );
    await expectLater(
      service.canonicalize(amount: -1, currency: 'EUR'),
      throwsArgumentError,
    );
    expect(calls, 0);
  });

  test('rejects malformed currency before any FX request', () async {
    var calls = 0;
    final service = PortfolioReferenceCapitalCanonicalizationService(
      loadCurrentFxRate: ({required baseCurrency, required quoteCurrency}) async {
        calls += 1;
        return fx(base: baseCurrency, quote: quoteCurrency, rate: 1);
      },
    );

    await expectLater(
      service.canonicalize(amount: 10000, currency: 'EURO'),
      throwsArgumentError,
    );
    expect(calls, 0);
  });
}
