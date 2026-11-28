import 'package:flutter_test/flutter_test.dart';
import 'package:app/features/market/presentation/widgets/verified_market_quote_panel.dart';

void main() {
  test('market quotes require a declared three-letter uppercase currency', () {
    expect(hasDeclaredQuoteCurrency('USD'), isTrue);
    expect(hasDeclaredQuoteCurrency('EUR'), isTrue);
    for (final invalid in <String?>[null, '', ' ', 'usd', 'US', 'USDD', 'USD ', 'U\nD']) {
      expect(hasDeclaredQuoteCurrency(invalid), isFalse, reason: 'invalid currency: $invalid');
    }
  });
}
