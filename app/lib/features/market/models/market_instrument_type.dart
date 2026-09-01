/// Tipo de instrumento negociado.
///
/// ATHENA TYCHE debe distinguir el instrumento de la empresa emisora.
/// Una misma empresa puede tener múltiples instrumentos y listados.
enum MarketInstrumentType {
  commonStock,
  preferredStock,
  adr,
  cdr,
  sdr,
  depositaryReceipt,
  etf,
  fund,
  unknown,
}

extension MarketInstrumentTypeExtension on MarketInstrumentType {
  String get key {
    switch (this) {
      case MarketInstrumentType.commonStock:
        return 'common_stock';

      case MarketInstrumentType.preferredStock:
        return 'preferred_stock';

      case MarketInstrumentType.adr:
        return 'adr';

      case MarketInstrumentType.cdr:
        return 'cdr';

      case MarketInstrumentType.sdr:
        return 'sdr';

      case MarketInstrumentType.depositaryReceipt:
        return 'depositary_receipt';

      case MarketInstrumentType.etf:
        return 'etf';

      case MarketInstrumentType.fund:
        return 'fund';

      case MarketInstrumentType.unknown:
        return 'unknown';
    }
  }
}
