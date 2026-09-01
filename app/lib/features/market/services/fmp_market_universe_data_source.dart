import 'dart:convert';

import '../../analysis/data/datasources/fmp_api_client.dart';
import '../models/market_universe_asset.dart';

/// Fuente de datos del universo global de mercado de FMP.
///
/// Responsabilidades:
/// - solicitar las páginas del Company Screener de FMP;
/// - recorrer el universo disponible;
/// - convertir las respuestas JSON a MarketUniverseAsset;
/// - eliminar únicamente duplicados del mismo listado.
///
/// No contiene:
/// - reglas de inversión;
/// - puntuaciones;
/// - recomendaciones;
/// - lógica de análisis.
///
/// La deduplicación se realiza mediante [MarketUniverseAsset.listingKey]
/// y no únicamente mediante el símbolo.
///
/// Esto es importante porque un mismo ticker puede existir en
/// diferentes mercados o listados.
class FmpMarketUniverseDataSource {
  final FmpApiClient apiClient;

  /// Número de activos solicitados por página a FMP.
  ///
  /// Este valor NO representa el tamaño máximo del universo.
  /// El universo se construye recorriendo las páginas disponibles.
  final int pageSize;

  const FmpMarketUniverseDataSource({
    required this.apiClient,
    this.pageSize = 1000,
  });

  /// Obtiene el universo completo de activos negociados activamente.
  ///
  /// La descarga termina cuando:
  ///
  /// - FMP devuelve una página vacía; o
  /// - FMP devuelve una página con menos elementos que [pageSize].
  ///
  /// Los duplicados inequívocos del mismo listado se eliminan mediante
  /// [MarketUniverseAsset.listingKey].
  Future<List<MarketUniverseAsset>> getUniverse() async {
    final assetsByListing = <String, MarketUniverseAsset>{};

    var page = 0;

    while (true) {
      final response = await apiClient.getCompanyScreenerPage(
        page: page,
        limit: pageSize,
      );

      if (response.statusCode != 200) {
        throw Exception(
          'FMP respondió con código HTTP '
          '${response.statusCode} al obtener el universo de mercado.',
        );
      }

      final dynamic decoded = jsonDecode(response.body);

      if (decoded is! List) {
        throw Exception(
          'FMP devolvió un formato inesperado para el universo de mercado.',
        );
      }

      if (decoded.isEmpty) {
        break;
      }

      for (final item in decoded) {
        if (item is! Map) {
          continue;
        }

        final asset = _mapAsset(
          Map<String, dynamic>.from(item),
        );

        if (asset == null) {
          continue;
        }

        assetsByListing[asset.listingKey] = asset;
      }

      if (decoded.length < pageSize) {
        break;
      }

      page++;
    }

    return assetsByListing.values.toList(growable: false);
  }

  MarketUniverseAsset? _mapAsset(
    Map<String, dynamic> json,
  ) {
    final symbol = _string(json['symbol']);
    final companyName = _string(json['companyName']);

    if (symbol == null || companyName == null) {
      return null;
    }

    return MarketUniverseAsset(
      symbol: symbol,
      companyName: companyName,
      marketCap: _double(json['marketCap']),
      country: _string(json['country']),
      exchange: _string(json['exchange']),
      exchangeShortName: _string(
        json['exchangeShortName'],
      ),
      sector: _string(json['sector']),
      industry: _string(json['industry']),
    );
  }

  double? _double(dynamic value) {
    if (value is num) {
      return value.toDouble();
    }

    if (value is String) {
      return double.tryParse(value);
    }

    return null;
  }

  String? _string(dynamic value) {
    if (value is! String) {
      return null;
    }

    final normalized = value.trim();

    if (normalized.isEmpty) {
      return null;
    }

    return normalized;
  }
}