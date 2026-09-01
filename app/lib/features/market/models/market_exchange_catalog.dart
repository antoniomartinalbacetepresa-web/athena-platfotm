import 'market_exchange.dart';

/// Catálogo de mercados y bolsas relevantes para ATHENA TYCHE.
///
/// Este catálogo es deliberadamente independiente de la obtención
/// de datos. Su función es describir la estructura del mercado.
///
/// Los códigos [yahooCode] corresponden a los exchanges utilizados
/// por Yahoo Finance/yfinance.
class MarketExchangeCatalog {
  const MarketExchangeCatalog._();

  static const List<MarketExchange> all = [
    // ============================================================
    // AMÉRICA
    // ============================================================

    MarketExchange(
      countryCode: 'US',
      countryName: 'Estados Unidos',
      regionKey: 'america',
      yahooCode: 'NYQ',
      name: 'New York Stock Exchange',
    ),
    MarketExchange(
      countryCode: 'US',
      countryName: 'Estados Unidos',
      regionKey: 'america',
      yahooCode: 'NMS',
      name: 'Nasdaq Global Market',
    ),
    MarketExchange(
      countryCode: 'US',
      countryName: 'Estados Unidos',
      regionKey: 'america',
      yahooCode: 'ASE',
      name: 'NYSE American',
    ),
    MarketExchange(
      countryCode: 'US',
      countryName: 'Estados Unidos',
      regionKey: 'america',
      yahooCode: 'NCM',
      name: 'Nasdaq Capital Market',
      isPrimaryMarket: false,
    ),
    MarketExchange(
      countryCode: 'US',
      countryName: 'Estados Unidos',
      regionKey: 'america',
      yahooCode: 'NGM',
      name: 'Nasdaq Global Select Market',
      isPrimaryMarket: false,
    ),

    MarketExchange(
      countryCode: 'CA',
      countryName: 'Canadá',
      regionKey: 'america',
      yahooCode: 'TOR',
      name: 'Toronto Stock Exchange',
    ),
    MarketExchange(
      countryCode: 'CA',
      countryName: 'Canadá',
      regionKey: 'america',
      yahooCode: 'VAN',
      name: 'TSX Venture Exchange',
    ),
    MarketExchange(
      countryCode: 'CA',
      countryName: 'Canadá',
      regionKey: 'america',
      yahooCode: 'NEO',
      name: 'Cboe Canada / NEO',
    ),

    MarketExchange(
      countryCode: 'MX',
      countryName: 'México',
      regionKey: 'america',
      yahooCode: 'MEX',
      name: 'Bolsa Mexicana de Valores',
    ),

    MarketExchange(
      countryCode: 'BR',
      countryName: 'Brasil',
      regionKey: 'america',
      yahooCode: 'SAO',
      name: 'B3',
    ),

    MarketExchange(
      countryCode: 'CL',
      countryName: 'Chile',
      regionKey: 'america',
      yahooCode: 'SGO',
      name: 'Santiago Stock Exchange',
    ),

    MarketExchange(
      countryCode: 'CO',
      countryName: 'Colombia',
      regionKey: 'america',
      yahooCode: 'BVC',
      name: 'Bolsa de Valores de Colombia',
    ),

    // ============================================================
    // EUROPA
    // ============================================================

    MarketExchange(
      countryCode: 'GB',
      countryName: 'Reino Unido',
      regionKey: 'europe',
      yahooCode: 'LSE',
      name: 'London Stock Exchange',
    ),
    MarketExchange(
      countryCode: 'GB',
      countryName: 'Reino Unido',
      regionKey: 'europe',
      yahooCode: 'IOB',
      name: 'International Order Book',
      isPrimaryMarket: false,
    ),
    MarketExchange(
      countryCode: 'GB',
      countryName: 'Reino Unido',
      regionKey: 'europe',
      yahooCode: 'AQS',
      name: 'Aquis Stock Exchange',
      isPrimaryMarket: false,
    ),

    MarketExchange(
      countryCode: 'DE',
      countryName: 'Alemania',
      regionKey: 'europe',
      yahooCode: 'GER',
      name: 'Xetra / Germany',
    ),
    MarketExchange(
      countryCode: 'DE',
      countryName: 'Alemania',
      regionKey: 'europe',
      yahooCode: 'FRA',
      name: 'Frankfurt Stock Exchange',
      isPrimaryMarket: false,
    ),
    MarketExchange(
      countryCode: 'DE',
      countryName: 'Alemania',
      regionKey: 'europe',
      yahooCode: 'STU',
      name: 'Stuttgart Stock Exchange',
      isPrimaryMarket: false,
    ),

    MarketExchange(
      countryCode: 'FR',
      countryName: 'Francia',
      regionKey: 'europe',
      yahooCode: 'PAR',
      name: 'Euronext Paris',
    ),
    MarketExchange(
      countryCode: 'FR',
      countryName: 'Francia',
      regionKey: 'europe',
      yahooCode: 'ENX',
      name: 'Euronext',
      isPrimaryMarket: false,
    ),

    MarketExchange(
      countryCode: 'ES',
      countryName: 'España',
      regionKey: 'europe',
      yahooCode: 'MCE',
      name: 'Bolsas y Mercados Españoles',
    ),
    MarketExchange(
      countryCode: 'ES',
      countryName: 'España',
      regionKey: 'europe',
      yahooCode: 'MAD',
      name: 'Bolsa de Madrid',
      isPrimaryMarket: false,
    ),

    MarketExchange(
      countryCode: 'IT',
      countryName: 'Italia',
      regionKey: 'europe',
      yahooCode: 'MIL',
      name: 'Euronext Milan',
    ),

    MarketExchange(
      countryCode: 'CH',
      countryName: 'Suiza',
      regionKey: 'europe',
      yahooCode: 'EBS',
      name: 'SIX Swiss Exchange',
    ),

    MarketExchange(
      countryCode: 'NL',
      countryName: 'Países Bajos',
      regionKey: 'europe',
      yahooCode: 'AMS',
      name: 'Euronext Amsterdam',
    ),

    MarketExchange(
      countryCode: 'BE',
      countryName: 'Bélgica',
      regionKey: 'europe',
      yahooCode: 'BRU',
      name: 'Euronext Brussels',
    ),

    MarketExchange(
      countryCode: 'DK',
      countryName: 'Dinamarca',
      regionKey: 'europe',
      yahooCode: 'CPH',
      name: 'Nasdaq Copenhagen',
    ),

    MarketExchange(
      countryCode: 'SE',
      countryName: 'Suecia',
      regionKey: 'europe',
      yahooCode: 'STO',
      name: 'Nasdaq Stockholm',
    ),

    MarketExchange(
      countryCode: 'NO',
      countryName: 'Noruega',
      regionKey: 'europe',
      yahooCode: 'OSL',
      name: 'Oslo Stock Exchange',
    ),

    MarketExchange(
      countryCode: 'FI',
      countryName: 'Finlandia',
      regionKey: 'europe',
      yahooCode: 'HEL',
      name: 'Nasdaq Helsinki',
    ),

    MarketExchange(
      countryCode: 'PL',
      countryName: 'Polonia',
      regionKey: 'europe',
      yahooCode: 'WSE',
      name: 'Warsaw Stock Exchange',
    ),

    MarketExchange(
      countryCode: 'PT',
      countryName: 'Portugal',
      regionKey: 'europe',
      yahooCode: 'LIS',
      name: 'Euronext Lisbon',
    ),

    MarketExchange(
      countryCode: 'AT',
      countryName: 'Austria',
      regionKey: 'europe',
      yahooCode: 'VIE',
      name: 'Vienna Stock Exchange',
    ),

    MarketExchange(
      countryCode: 'GR',
      countryName: 'Grecia',
      regionKey: 'europe',
      yahooCode: 'ATH',
      name: 'Athens Stock Exchange',
    ),

    MarketExchange(
      countryCode: 'IE',
      countryName: 'Irlanda',
      regionKey: 'europe',
      yahooCode: 'ISE',
      name: 'Euronext Dublin',
    ),

    // ============================================================
    // ASIA
    // ============================================================

    MarketExchange(
      countryCode: 'JP',
      countryName: 'Japón',
      regionKey: 'asia',
      yahooCode: 'JPX',
      name: 'Japan Exchange Group',
    ),
    MarketExchange(
      countryCode: 'JP',
      countryName: 'Japón',
      regionKey: 'asia',
      yahooCode: 'OSA',
      name: 'Osaka Exchange',
      isPrimaryMarket: false,
    ),
    MarketExchange(
      countryCode: 'JP',
      countryName: 'Japón',
      regionKey: 'asia',
      yahooCode: 'SAP',
      name: 'Sapporo Securities Exchange',
      isPrimaryMarket: false,
    ),

    MarketExchange(
      countryCode: 'HK',
      countryName: 'Hong Kong',
      regionKey: 'asia',
      yahooCode: 'HKG',
      name: 'Hong Kong Stock Exchange',
    ),

    MarketExchange(
      countryCode: 'CN',
      countryName: 'China',
      regionKey: 'asia',
      yahooCode: 'SHH',
      name: 'Shanghai Stock Exchange',
    ),
    MarketExchange(
      countryCode: 'CN',
      countryName: 'China',
      regionKey: 'asia',
      yahooCode: 'SHZ',
      name: 'Shenzhen Stock Exchange',
    ),

    MarketExchange(
      countryCode: 'KR',
      countryName: 'Corea del Sur',
      regionKey: 'asia',
      yahooCode: 'KSC',
      name: 'Korea Exchange',
    ),
    MarketExchange(
      countryCode: 'KR',
      countryName: 'Corea del Sur',
      regionKey: 'asia',
      yahooCode: 'KOE',
      name: 'Korea Exchange',
      isPrimaryMarket: false,
    ),

    MarketExchange(
      countryCode: 'TW',
      countryName: 'Taiwán',
      regionKey: 'asia',
      yahooCode: 'TAI',
      name: 'Taiwan Stock Exchange',
    ),
    MarketExchange(
      countryCode: 'TW',
      countryName: 'Taiwán',
      regionKey: 'asia',
      yahooCode: 'TWO',
      name: 'Taipei Exchange',
      isPrimaryMarket: false,
    ),

    MarketExchange(
      countryCode: 'IN',
      countryName: 'India',
      regionKey: 'asia',
      yahooCode: 'BSE',
      name: 'BSE India',
    ),
    MarketExchange(
      countryCode: 'IN',
      countryName: 'India',
      regionKey: 'asia',
      yahooCode: 'NSI',
      name: 'National Stock Exchange of India',
    ),

    MarketExchange(
      countryCode: 'SG',
      countryName: 'Singapur',
      regionKey: 'asia',
      yahooCode: 'SES',
      name: 'Singapore Exchange',
    ),

    MarketExchange(
      countryCode: 'MY',
      countryName: 'Malasia',
      regionKey: 'asia',
      yahooCode: 'KLS',
      name: 'Bursa Malaysia',
    ),

    MarketExchange(
      countryCode: 'TH',
      countryName: 'Tailandia',
      regionKey: 'asia',
      yahooCode: 'SET',
      name: 'Stock Exchange of Thailand',
    ),

    MarketExchange(
      countryCode: 'ID',
      countryName: 'Indonesia',
      regionKey: 'asia',
      yahooCode: 'JKT',
      name: 'Indonesia Stock Exchange',
    ),

    MarketExchange(
      countryCode: 'VN',
      countryName: 'Vietnam',
      regionKey: 'asia',
      yahooCode: 'VSE',
      name: 'Vietnam Stock Exchange',
    ),

    MarketExchange(
      countryCode: 'PH',
      countryName: 'Filipinas',
      regionKey: 'asia',
      yahooCode: 'PHS',
      name: 'Philippine Stock Exchange',
    ),

    MarketExchange(
      countryCode: 'IL',
      countryName: 'Israel',
      regionKey: 'asia',
      yahooCode: 'TLV',
      name: 'Tel Aviv Stock Exchange',
    ),

    // ============================================================
    // OCEANÍA
    // ============================================================

    MarketExchange(
      countryCode: 'AU',
      countryName: 'Australia',
      regionKey: 'asia',
      yahooCode: 'ASX',
      name: 'Australian Securities Exchange',
    ),

    MarketExchange(
      countryCode: 'NZ',
      countryName: 'Nueva Zelanda',
      regionKey: 'asia',
      yahooCode: 'NZE',
      name: 'New Zealand Exchange',
    ),

    // ============================================================
    // ORIENTE MEDIO / ÁFRICA
    // ============================================================

    MarketExchange(
      countryCode: 'SA',
      countryName: 'Arabia Saudí',
      regionKey: 'asia',
      yahooCode: 'SAU',
      name: 'Saudi Exchange',
    ),

    MarketExchange(
      countryCode: 'AE',
      countryName: 'Emiratos Árabes Unidos',
      regionKey: 'asia',
      yahooCode: 'DFM',
      name: 'Dubai Financial Market',
    ),

    MarketExchange(
      countryCode: 'QA',
      countryName: 'Catar',
      regionKey: 'asia',
      yahooCode: 'DOH',
      name: 'Qatar Stock Exchange',
    ),

    MarketExchange(
      countryCode: 'ZA',
      countryName: 'Sudáfrica',
      regionKey: 'africa',
      yahooCode: 'JNB',
      name: 'Johannesburg Stock Exchange',
    ),
  ];

  static MarketExchange? findByYahooCode(String code) {
    final normalized = code.trim().toUpperCase();

    for (final exchange in all) {
      if (exchange.yahooCode == normalized) {
        return exchange;
      }
    }

    return null;
  }

  static List<MarketExchange> byRegion(String regionKey) {
    final normalized = regionKey.trim().toLowerCase();

    return all
        .where(
          (exchange) =>
              exchange.regionKey.toLowerCase() == normalized,
        )
        .toList(growable: false);
  }

  static List<MarketExchange> byCountry(String countryCode) {
    final normalized = countryCode.trim().toUpperCase();

    return all
        .where(
          (exchange) =>
              exchange.countryCode.toUpperCase() == normalized,
        )
        .toList(growable: false);
  }
}
