import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../models/market_instrument_type.dart';
import '../../models/market_universe_asset.dart';

/// Fuente de datos del universo global proporcionado por el backend
/// de ATHENA TYCHE.
///
/// Flutter no necesita conocer qué proveedores externos se han utilizado
/// para construir el universo.
///
/// El backend es responsable de recopilar, normalizar y combinar las
/// distintas fuentes disponibles. Esta clase únicamente transforma el
/// contrato HTTP normalizado en objetos [MarketUniverseAsset].
class AthenaBackendMarketUniverseDataSource {
  final String baseUrl;
  final http.Client client;

  AthenaBackendMarketUniverseDataSource({
    required this.baseUrl,
    http.Client? client,
  }) : client = client ?? http.Client();

  /// Obtiene el universo global disponible en el backend.
  ///
  /// Los duplicados inequívocos del mismo listado se eliminan mediante
  /// [MarketUniverseAsset.listingKey].
  ///
  /// No se fusionan automáticamente instrumentos pertenecientes a un mismo
  /// emisor. Esa decisión requiere información fiable de [issuerId].
  Future<List<MarketUniverseAsset>> getUniverse() async {
    final uri = Uri.parse('$baseUrl/api/v1/market/universe');

    final response = await client.get(uri);

    _validateResponse(response);

    final decoded = _decodeObject(response.body);

    final data = decoded['data'];

    if (data == null) {
      return const [];
    }

    if (data is! List) {
      throw const FormatException(
        'La respuesta del universo del backend '
        'no contiene una lista válida.',
      );
    }

    final assetsByListing = <String, MarketUniverseAsset>{};

    for (final item in data) {
      if (item is! Map) {
        continue;
      }

      final asset = _mapAsset(Map<String, dynamic>.from(item));

      if (asset == null) {
        continue;
      }

      assetsByListing[asset.listingKey] = asset;
    }

    return assetsByListing.values.toList(growable: false);
  }

  MarketUniverseAsset? _mapAsset(Map<String, dynamic> json) {
    final symbol = _string(json['symbol']);
    final companyName = _string(json['companyName']);

    if (symbol == null || companyName == null) {
      return null;
    }

    return MarketUniverseAsset(
      symbol: symbol.toUpperCase(),
      companyName: companyName,
      marketCap: _double(json['marketCap']),
      country: _string(json['country']),
      exchange: _string(json['exchange']),
      exchangeShortName: _string(json['exchangeShortName']),
      regionKey: _string(json['regionKey']),
      issuerId: _string(json['issuerId']),
      instrumentId: _string(json['instrumentId']),
      instrumentType: _instrumentType(json['instrumentType']),
      isPrimaryListing: _bool(json['isPrimaryListing']),
      sector: _string(json['sector']),
      industry: _string(json['industry']),
    );
  }

  MarketInstrumentType _instrumentType(dynamic value) {
    final normalized = _string(value)?.toLowerCase();

    switch (normalized) {
      case 'common_stock':
        return MarketInstrumentType.commonStock;

      case 'preferred_stock':
        return MarketInstrumentType.preferredStock;

      case 'adr':
        return MarketInstrumentType.adr;

      case 'cdr':
        return MarketInstrumentType.cdr;

      case 'sdr':
        return MarketInstrumentType.sdr;

      case 'depositary_receipt':
        return MarketInstrumentType.depositaryReceipt;

      case 'etf':
        return MarketInstrumentType.etf;

      case 'fund':
        return MarketInstrumentType.fund;

      default:
        return MarketInstrumentType.unknown;
    }
  }

  bool? _bool(dynamic value) {
    if (value is bool) {
      return value;
    }

    if (value is num) {
      if (value == 1) {
        return true;
      }

      if (value == 0) {
        return false;
      }
    }

    if (value is String) {
      switch (value.trim().toLowerCase()) {
        case 'true':
        case '1':
          return true;

        case 'false':
        case '0':
          return false;
      }
    }

    return null;
  }

  double? _double(dynamic value) {
    if (value is num) {
      return value.toDouble();
    }

    if (value is String) {
      return double.tryParse(value.trim());
    }

    return null;
  }

  String? _string(dynamic value) {
    if (value == null) {
      return null;
    }

    final normalized = value.toString().trim();

    if (normalized.isEmpty) {
      return null;
    }

    return normalized;
  }

  void _validateResponse(http.Response response) {
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(
        'El backend de ATHENA TYCHE respondió '
        'con código HTTP ${response.statusCode} '
        'al obtener el universo de mercado.',
      );
    }
  }

  Map<String, dynamic> _decodeObject(String body) {
    final decoded = jsonDecode(body);

    if (decoded is! Map<String, dynamic>) {
      throw const FormatException(
        'La respuesta del universo del backend '
        'no es un objeto JSON válido.',
      );
    }

    return decoded;
  }

  void dispose() {
    client.close();
  }
}
