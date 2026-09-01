import 'package:flutter_test/flutter_test.dart';
import 'package:app/features/market/services/mock_market_service.dart';

void main() {
  test('MockMarketService normaliza el símbolo', () async {
    const service = MockMarketService();

    final quote = await service.getQuote('  aapl  ');

    expect(quote.symbol, 'AAPL');
    expect(quote.companyName, 'Apple Inc.');
  });

  test('MockMarketService rechaza un símbolo vacío', () async {
    const service = MockMarketService();

    expect(
      () => service.getQuote('   '),
      throwsArgumentError,
    );
  });

  test('MockMarketService devuelve datos de prueba válidos', () async {
    const service = MockMarketService();

    final quote = await service.getQuote('MSFT');

    expect(quote.symbol, 'MSFT');
    expect(quote.companyName, 'Empresa de prueba');
    expect(quote.currentPrice, 226.40);
    expect(quote.change, 2.15);
    expect(quote.changePercentage, 0.96);
  });
}