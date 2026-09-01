/// Representa un mercado o bolsa que ATHENA TYCHE puede utilizar
/// para clasificar instrumentos financieros.
///
/// El código [yahooCode] corresponde al código de exchange utilizado
/// por Yahoo Finance/yfinance para consultas de mercado.
///
/// Importante:
/// - yahooCode identifica el mercado dentro de Yahoo;
/// - no debe confundirse con el ticker del instrumento;
/// - tampoco implica que todos los instrumentos de ese mercado
///   sean acciones ordinarias.
class MarketExchange {
  final String countryCode;
  final String countryName;
  final String regionKey;
  final String yahooCode;
  final String name;
  final bool isPrimaryMarket;

  const MarketExchange({
    required this.countryCode,
    required this.countryName,
    required this.regionKey,
    required this.yahooCode,
    required this.name,
    this.isPrimaryMarket = true,
  });

  @override
  String toString() {
    return 'MarketExchange('
        'countryCode: $countryCode, '
        'countryName: $countryName, '
        'regionKey: $regionKey, '
        'yahooCode: $yahooCode, '
        'name: $name, '
        'isPrimaryMarket: $isPrimaryMarket'
        ')';
  }
}
