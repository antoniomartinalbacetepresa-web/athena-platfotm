import 'market_instrument_type.dart';

/// Representa un instrumento perteneciente al universo de mercado
/// utilizado por ATHENA TYCHE.
///
/// IMPORTANTE:
///
/// Un instrumento/listado NO es necesariamente una empresa.
///
/// Ejemplo:
///
/// NVDA
/// NVDA.TO
/// NVDA.NE
/// NVD.DE
/// NVDA.SW
///
/// pueden representar exposiciones/listados relacionados con
/// el mismo emisor.
///
/// Por este motivo ATHENA TYCHE separa:
///
/// - issuerId       -> identificador del emisor, si está disponible;
/// - instrumentId   -> identificador del instrumento, si está disponible;
/// - symbol         -> ticker concreto;
/// - exchange       -> mercado donde cotiza.
///
/// La identificación automática del emisor se mantendrá conservadora.
/// No se fusionarán empresas únicamente porque tengan nombres parecidos.
class MarketUniverseAsset {
  final String symbol;
  final String companyName;

  final double? marketCap;

  /// Código de país ISO cuando la fuente lo proporciona.
  final String? country;

  /// Nombre o descripción de la bolsa.
  final String? exchange;

  /// Código de exchange utilizado por la fuente.
  ///
  /// Para Yahoo Finance corresponde normalmente al código
  /// utilizado por su screener, por ejemplo:
  /// NMS, NYQ, LSE, JPX, HKG, TAI, etc.
  final String? exchangeShortName;

  /// Región estructural de ATHENA TYCHE.
  final String? regionKey;

  /// Identificador estable del emisor cuando pueda determinarse
  /// con suficiente confianza.
  final String? issuerId;

  /// Identificador estable del instrumento cuando la fuente
  /// lo proporcione.
  final String? instrumentId;

  /// Tipo de instrumento.
  final MarketInstrumentType instrumentType;

  /// Indica si el listado se considera la cotización principal
  /// del instrumento/emisor.
  ///
  /// Puede ser null cuando todavía no disponemos de información
  /// suficiente para determinarlo.
  final bool? isPrimaryListing;

  final String? sector;
  final String? industry;

  const MarketUniverseAsset({
    required this.symbol,
    required this.companyName,
    this.marketCap,
    this.country,
    this.exchange,
    this.exchangeShortName,
    this.regionKey,
    this.issuerId,
    this.instrumentId,
    this.instrumentType = MarketInstrumentType.unknown,
    this.isPrimaryListing,
    this.sector,
    this.industry,
  });

  bool get hasMarketCap {
    return marketCap != null && marketCap! > 0;
  }

  bool get isValid {
    return symbol.trim().isNotEmpty &&
        companyName.trim().isNotEmpty;
  }

  /// Identificador del listado concreto.
  ///
  /// No intenta identificar a la empresa.
  ///
  /// Esto evita fusionar accidentalmente:
  ///
  /// AAPL
  /// AAPL.MX
  /// AAPL.NE
  /// etc.
  String get listingKey {
    final normalizedSymbol = symbol.trim().toUpperCase();
    final normalizedExchange =
        (exchangeShortName ?? exchange ?? '')
            .trim()
            .toUpperCase();

    if (normalizedExchange.isEmpty) {
      return normalizedSymbol;
    }

    return '$normalizedSymbol@$normalizedExchange';
  }

  /// Identificador de agrupación del emisor.
  ///
  /// Solo se considera fiable cuando [issuerId] ha sido proporcionado
  /// explícitamente por una fuente o por una capa de normalización
  /// suficientemente fiable.
  ///
  /// No se genera automáticamente a partir del nombre de la empresa.
  String? get issuerKey {
    final value = issuerId?.trim();

    if (value == null || value.isEmpty) {
      return null;
    }

    return value;
  }

  MarketUniverseAsset copyWith({
    String? symbol,
    String? companyName,
    double? marketCap,
    String? country,
    String? exchange,
    String? exchangeShortName,
    String? regionKey,
    String? issuerId,
    String? instrumentId,
    MarketInstrumentType? instrumentType,
    bool? isPrimaryListing,
    String? sector,
    String? industry,
  }) {
    return MarketUniverseAsset(
      symbol: symbol ?? this.symbol,
      companyName: companyName ?? this.companyName,
      marketCap: marketCap ?? this.marketCap,
      country: country ?? this.country,
      exchange: exchange ?? this.exchange,
      exchangeShortName:
          exchangeShortName ?? this.exchangeShortName,
      regionKey: regionKey ?? this.regionKey,
      issuerId: issuerId ?? this.issuerId,
      instrumentId: instrumentId ?? this.instrumentId,
      instrumentType:
          instrumentType ?? this.instrumentType,
      isPrimaryListing:
          isPrimaryListing ?? this.isPrimaryListing,
      sector: sector ?? this.sector,
      industry: industry ?? this.industry,
    );
  }

  @override
  String toString() {
    return 'MarketUniverseAsset('
        'symbol: $symbol, '
        'companyName: $companyName, '
        'marketCap: $marketCap, '
        'country: $country, '
        'exchange: $exchange, '
        'exchangeShortName: $exchangeShortName, '
        'regionKey: $regionKey, '
        'issuerId: $issuerId, '
        'instrumentId: $instrumentId, '
        'instrumentType: ${instrumentType.key}, '
        'isPrimaryListing: $isPrimaryListing, '
        'sector: $sector, '
        'industry: $industry'
        ')';
  }
}
