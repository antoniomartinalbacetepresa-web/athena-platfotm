/// Validates market-price provenance before Portfolio exposes a valuation.
/// A nonempty provider label does not establish an allowed free source.
class MarketSourceProvenance {
  const MarketSourceProvenance._();

  static void requireAllowed(String? value) {
    final provider = value?.trim() ?? '';
    if (provider.isEmpty ||
        provider.codeUnits.any((unit) => unit < 32 || unit > 126) ||
        provider.contains('%') ||
        provider.contains('&') ||
        provider.contains('\\')) {
      throw StateError('La procedencia de mercado no es verificable.');
    }
    final key = provider.toLowerCase().replaceAll(RegExp(r'[^a-z0-9]'), '');
    if (key.isEmpty ||
        key.contains('fmp') ||
        key.contains('financialmodelingprep')) {
      throw StateError('La fuente de mercado no está permitida.');
    }
  }
}
