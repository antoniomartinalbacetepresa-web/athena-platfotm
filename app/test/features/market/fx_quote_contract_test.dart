import 'package:app/features/market/models/fx_quote.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  Map<String, dynamic> currentQuote() => {
        'status': 'fx_current_ready',
        'baseCurrency': 'USD',
        'quoteCurrency': 'EUR',
        'rate': 0.85,
        'observedAt': '2026-08-15T00:00:00Z',
        'retrievedAt': '2026-08-15T00:00:01Z',
        'sourceProvider': 'yahoo',
        'sourceSymbol': 'USDEUR=X',
        'historicalPointInTimeEligible': false,
      };

  test('whitespace cannot disguise identity as a market FX provider', () {
    for (final provider in [' identity ', 'IDENTITY ']) {
      final payload = currentQuote()..['sourceProvider'] = provider;
      expect(() => FxQuote.fromMap(payload), throwsArgumentError);
    }
  });

  test('same-currency identity uses normalized provider consistently', () {
    final payload = currentQuote()
      ..['status'] = 'fx_identity'
      ..['baseCurrency'] = 'EUR'
      ..['quoteCurrency'] = 'EUR'
      ..['rate'] = 1.0
      ..['sourceProvider'] = ' identity '
      ..['sourceSymbol'] = null;
    final quote = FxQuote.fromMap(payload);
    expect(quote.sourceProvider, 'identity');
    expect(quote.isIdentity, isTrue);
  });

  test('provider control characters cannot disappear during trimming', () {
    for (final provider in ['yahoo\n', 'yahoo\t']) {
      final payload = currentQuote()..['sourceProvider'] = provider;
      expect(() => FxQuote.fromMap(payload), throwsArgumentError);
    }
  });

  test('validated FX status is canonical for downstream consumers', () {
    final payload = currentQuote()..['status'] = ' FX_CURRENT_READY ';
    final quote = FxQuote.fromMap(payload);
    expect(quote.status, 'fx_current_ready');
    expect(quote.convertCurrent(100), 85);
  });

  test('identity provider casing cannot alter the canonical identity contract', () {
    final payload = currentQuote()
      ..['status'] = ' FX_IDENTITY '
      ..['baseCurrency'] = 'EUR'
      ..['quoteCurrency'] = 'EUR'
      ..['rate'] = 1.0
      ..['sourceProvider'] = 'IDENTITY'
      ..['sourceSymbol'] = null;
    final quote = FxQuote.fromMap(payload);
    expect(quote.status, 'fx_identity');
    expect(quote.sourceProvider, 'identity');
    expect(quote.convertCurrent(100), 100);
  });

  test('valid current market conversion stays finite', () {
    final quote = FxQuote.fromMap(currentQuote());
    expect(quote.convertCurrent(100), 85);
  });

  test('unknown FX status cannot be used as a current valuation', () {
    final payload = currentQuote()..['status'] = 'fx_unavailable';
    expect(() => FxQuote.fromMap(payload), throwsArgumentError);
  });

  test('current market status cannot masquerade as identity', () {
    final payload = currentQuote()
      ..['baseCurrency'] = 'EUR'
      ..['quoteCurrency'] = 'EUR'
      ..['rate'] = 1.0
      ..['sourceProvider'] = 'identity'
      ..['sourceSymbol'] = null;
    expect(() => FxQuote.fromMap(payload), throwsArgumentError);
  });

  test('identity status cannot masquerade as a market FX quote', () {
    final payload = currentQuote()..['status'] = 'fx_identity';
    expect(() => FxQuote.fromMap(payload), throwsArgumentError);
  });

  test('historical market status cannot masquerade as identity', () {
    final payload = currentQuote()
      ..['status'] = 'fx_historical_ready'
      ..['historicalPointInTimeEligible'] = true
      ..['baseCurrency'] = 'EUR'
      ..['quoteCurrency'] = 'EUR'
      ..['rate'] = 1.0
      ..['sourceProvider'] = 'identity'
      ..['sourceSymbol'] = null;
    expect(() => FxQuote.fromMap(payload), throwsArgumentError);
  });

  test('historical identity status cannot masquerade as market FX', () {
    final payload = currentQuote()
      ..['status'] = 'fx_historical_identity'
      ..['historicalPointInTimeEligible'] = true;
    expect(() => FxQuote.fromMap(payload), throwsArgumentError);
  });

  test('historical identity remains eligible for PIT and not current conversion', () {
    final payload = currentQuote()
      ..['status'] = 'fx_historical_identity'
      ..['historicalPointInTimeEligible'] = true
      ..['baseCurrency'] = 'EUR'
      ..['quoteCurrency'] = 'EUR'
      ..['rate'] = 1.0
      ..['sourceProvider'] = 'identity'
      ..['sourceSymbol'] = null;
    final quote = FxQuote.fromMap(payload);
    expect(quote.isIdentity, isTrue);
    expect(quote.historicalPointInTimeEligible, isTrue);
    expect(() => quote.convertCurrent(10), throwsStateError);
  });

  test('historical conversion uses only PIT evidence and stays finite', () {
    final historical = currentQuote()
      ..['status'] = 'fx_historical_ready'
      ..['historicalPointInTimeEligible'] = true
      ..['rate'] = 2.0;
    final quote = FxQuote.fromMap(historical);
    expect(quote.convertHistorical(100), 200);
    expect(() => quote.convertHistorical(double.maxFinite), throwsStateError);
    expect(() => FxQuote.fromMap(currentQuote()).convertHistorical(100),
        throwsStateError);
  });

  test('missing PIT eligibility is not silently treated as current', () {
    final payload = currentQuote()..remove('historicalPointInTimeEligible');
    expect(() => FxQuote.fromMap(payload), throwsFormatException);
  });

  test('string PIT eligibility is rejected instead of coerced', () {
    final payload = currentQuote()..['historicalPointInTimeEligible'] = 'false';
    expect(() => FxQuote.fromMap(payload), throwsFormatException);
  });

  test('finite inputs producing infinite FX valuation fail closed', () {
    final payload = currentQuote()..['rate'] = 2.0;
    final quote = FxQuote.fromMap(payload);
    expect(() => quote.convertCurrent(double.maxFinite), throwsStateError);
  });
}
