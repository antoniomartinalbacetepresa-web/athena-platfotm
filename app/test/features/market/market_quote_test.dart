import 'package:flutter_test/flutter_test.dart';
import 'package:app/features/market/models/market_quote.dart';

void main() {
  test('MarketQuote identifica correctamente una variación positiva', () {
    final quote = MarketQuote(
      symbol: 'AAPL',
      companyName: 'Apple Inc.',
      currentPrice: 226.40,
      change: 2.15,
      changePercentage: 0.96,
      updatedAt: DateTime(2026, 8, 24),
    );

    expect(quote.isPositive, isTrue);
    expect(quote.isNegative, isFalse);
  });

  test('MarketQuote identifica correctamente una variación negativa', () {
    final quote = MarketQuote(
      symbol: 'AAPL',
      companyName: 'Apple Inc.',
      currentPrice: 220.00,
      change: -3.50,
      changePercentage: -1.56,
      updatedAt: DateTime(2026, 8, 24),
    );

    expect(quote.isPositive, isFalse);
    expect(quote.isNegative, isTrue);
  });

  test('MarketQuote convierte correctamente a JSON y desde JSON', () {
    final original = MarketQuote(
      symbol: 'AAPL',
      companyName: 'Apple Inc.',
      currentPrice: 226.40,
      change: 2.15,
      changePercentage: 0.96,
      updatedAt: DateTime(2026, 8, 24),
    );

    final json = original.toJson();
    final restored = MarketQuote.fromJson(json);

    expect(restored.symbol, original.symbol);
    expect(restored.companyName, original.companyName);
    expect(restored.currentPrice, original.currentPrice);
    expect(restored.change, original.change);
    expect(restored.changePercentage, original.changePercentage);
    expect(restored.updatedAt, original.updatedAt);
  });
}