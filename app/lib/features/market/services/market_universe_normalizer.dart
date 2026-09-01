import '../models/market_exchange_catalog.dart';
import '../models/market_instrument_type.dart';
import '../models/market_universe_asset.dart';

/// Normaliza activos del universo global.
///
/// Responsabilidades:
///
/// - identificar el mercado de Yahoo cuando sea posible;
/// - asignar región;
/// - conservar el listado concreto;
/// - eliminar únicamente duplicados inequívocos.
///
/// NO intenta fusionar empresas por nombre.
///
/// Esa decisión es deliberada:
/// "APPLE INC" y "APPLE INC CDR", por ejemplo, no deben fusionarse
/// sin evidencia suficiente de que representan exactamente el mismo
/// instrumento/emisor.
class MarketUniverseNormalizer {
  const MarketUniverseNormalizer();

  List<MarketUniverseAsset> normalize(
    List<MarketUniverseAsset> assets,
  ) {
    final normalizedByListing = <String, MarketUniverseAsset>{};

    for (final asset in assets) {
      if (!asset.isValid) {
        continue;
      }

      final normalized = normalizeAsset(asset);

      normalizedByListing[normalized.listingKey] = normalized;
    }

    return normalizedByListing.values.toList(growable: false);
  }

  MarketUniverseAsset normalizeAsset(
    MarketUniverseAsset asset,
  ) {
    final exchangeCode =
        asset.exchangeShortName?.trim().toUpperCase();

    if (exchangeCode == null || exchangeCode.isEmpty) {
      return asset;
    }

    final exchange =
        MarketExchangeCatalog.findByYahooCode(exchangeCode);

    if (exchange == null) {
      return asset;
    }

    final country =
        asset.country?.trim().isNotEmpty == true
            ? asset.country
            : exchange.countryCode;

    final regionKey =
        asset.regionKey?.trim().isNotEmpty == true
            ? asset.regionKey
            : exchange.regionKey;

    return asset.copyWith(
      country: country,
      regionKey: regionKey,
    );
  }

  /// Clasificación conservadora de instrumentos a partir de
  /// información textual.
  ///
  /// No sustituye una clasificación oficial de la fuente.
  MarketInstrumentType inferInstrumentType({
    String? symbol,
    String? companyName,
  }) {
    final normalizedSymbol =
        (symbol ?? '').trim().toUpperCase();

    final normalizedName =
        (companyName ?? '').trim().toUpperCase();

    final combined = '$normalizedSymbol $normalizedName';

    if (combined.contains(' CDR')) {
      return MarketInstrumentType.cdr;
    }

    if (combined.contains(' SDR')) {
      return MarketInstrumentType.sdr;
    }

    if (combined.contains(' ADR')) {
      return MarketInstrumentType.adr;
    }

    if (combined.contains(' DEPOSITARY RECEIPT') ||
        combined.contains(' DEPOSITARY RECEIPTS')) {
      return MarketInstrumentType.depositaryReceipt;
    }

    if (combined.contains(' ETF')) {
      return MarketInstrumentType.etf;
    }

    return MarketInstrumentType.unknown;
  }
}
