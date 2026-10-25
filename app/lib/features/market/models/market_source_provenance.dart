/// Validates market-price provenance before Portfolio exposes a valuation.
/// A nonempty provider label does not establish an allowed free source.
class MarketSourceProvenance {
  const MarketSourceProvenance._();

  static void requireAllowed(String? value) {
    // Validate the original bytes before trim: a trailing newline or control
    // character must not disappear from the provenance boundary.
    final raw = value ?? '';
    if (raw.codeUnits.any((unit) => unit < 32 || unit > 126) ||
        raw.contains('%') ||
        raw.contains('&') ||
        raw.contains('\\')) {
      throw StateError('La procedencia de mercado no es verificable.');
    }
    final provider = raw.trim();
    if (provider.isEmpty) {
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
