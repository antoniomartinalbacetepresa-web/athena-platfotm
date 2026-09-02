import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/market_data_point.dart';
import 'market_data_provider.dart';

/// Proveedor de datos de mercado procedentes del backend de ATHENA TYCHE.
///
/// Flutter no conoce ni expone claves de proveedores externos. El backend sí
/// puede declarar la fuente real utilizada y el instante de recuperación para
/// conservar provenance sin acoplar la aplicación cliente al proveedor.
class AthenaBackendMarketDataProvider implements MarketDataProvider {
  static const String _providerId = 'athena_backend';

  final String baseUrl;
  final http.Client client;

  AthenaBackendMarketDataProvider({required this.baseUrl, http.Client? client})
      : client = client ?? http.Client();

  @override
  String get providerId => _providerId;

  @override
  Future<MarketDataPoint?> getQuote(String symbol) async {
    final normalizedSymbol = _normalizeSymbol(symbol);

    final uri = Uri.parse(
      '$baseUrl/api/v1/market/quote',
    ).replace(queryParameters: {'symbol': normalizedSymbol});

    final response = await client.get(uri);

    _validateResponse(response);

    final decoded = _decodeObject(response.body);

    final data = decoded['data'];

    if (data == null) {
      return null;
    }

    if (data is! Map) {
      throw const FormatException(
        'La respuesta del backend no contiene una cotización válida.',
      );
    }

    return _mapPoint(
      data: Map<String, dynamic>.from(data),
      fallbackSymbol: normalizedSymbol,
    );
  }

  @override
  Future<List<MarketDataPoint>> getHistoricalData({
    required String symbol,
    DateTime? from,
    DateTime? to,
  }) async {
    final normalizedSymbol = _normalizeSymbol(symbol);

    final queryParameters = <String, String>{'symbol': normalizedSymbol};

    if (from != null) {
      queryParameters['from'] = _formatDate(from);
    }

    if (to != null) {
      queryParameters['to'] = _formatDate(to);
    }

    final uri = Uri.parse(
      '$baseUrl/api/v1/market/history',
    ).replace(queryParameters: queryParameters);

    final response = await client.get(uri);

    _validateResponse(response);

    final decoded = _decodeObject(response.body);

    final data = decoded['data'];

    if (data == null) {
      return const [];
    }

    if (data is! List) {
      throw const FormatException(
        'La respuesta histórica del backend no contiene una lista válida.',
      );
    }

    final result = <MarketDataPoint>[];

    for (final item in data) {
      if (item is! Map) {
        continue;
      }

      result.add(
        _mapPoint(
          data: Map<String, dynamic>.from(item),
          fallbackSymbol: normalizedSymbol,
        ),
      );
    }

    return result;
  }

  MarketDataPoint _mapPoint({
    required Map<String, dynamic> data,
    required String fallbackSymbol,
  }) {
    final timestamp = _parseTimestamp(data['timestamp']);
    final retrievedAt = _parseOptionalTimestamp(data['retrievedAt']);

    final symbol = data['symbol']?.toString().trim().toUpperCase();
    final sourceProvider = data['sourceProvider']?.toString().trim();

    return MarketDataPoint(
      symbol: symbol == null || symbol.isEmpty ? fallbackSymbol : symbol,
      timestamp: timestamp,
      open: _parseDouble(data['open']),
      high: _parseDouble(data['high']),
      low: _parseDouble(data['low']),
      close: _parseDouble(data['close']),
      adjustedClose: _parseDouble(data['adjustedClose']),
      volume: _parseDouble(data['volume']),
      change: _parseDouble(data['change']),
      changePercentage: _parseDouble(data['changePercentage']),
      providerId: providerId,
      sourceProvider:
          sourceProvider == null || sourceProvider.isEmpty ? null : sourceProvider,
      retrievedAt: retrievedAt,
    );
  }

  String _normalizeSymbol(String symbol) {
    final normalized = symbol.trim().toUpperCase();

    if (normalized.isEmpty) {
      throw ArgumentError.value(
        symbol,
        'symbol',
        'El símbolo no puede estar vacío.',
      );
    }

    return normalized;
  }

  void _validateResponse(http.Response response) {
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(
        'El backend de ATHENA TYCHE respondió con código HTTP '
        '${response.statusCode}.',
      );
    }
  }

  Map<String, dynamic> _decodeObject(String body) {
    final decoded = jsonDecode(body);

    if (decoded is! Map<String, dynamic>) {
      throw const FormatException(
        'La respuesta del backend de ATHENA TYCHE no es un objeto JSON válido.',
      );
    }

    return decoded;
  }

  double? _parseDouble(dynamic value) {
    if (value == null) {
      return null;
    }

    if (value is num) {
      return value.toDouble();
    }

    return double.tryParse(value.toString());
  }

  DateTime _parseTimestamp(dynamic value) {
    if (value == null) {
      throw const FormatException('El backend no proporcionó fecha/hora.');
    }

    final parsed = DateTime.tryParse(value.toString());

    if (parsed == null) {
      throw FormatException(
        'Fecha/hora inválida recibida del backend: $value',
      );
    }

    return parsed;
  }

  DateTime? _parseOptionalTimestamp(dynamic value) {
    if (value == null) {
      return null;
    }

    final parsed = DateTime.tryParse(value.toString());
    if (parsed == null) {
      throw FormatException(
        'Fecha/hora de recuperación inválida recibida del backend: $value',
      );
    }

    return parsed;
  }

  String _formatDate(DateTime value) {
    final year = value.year.toString().padLeft(4, '0');
    final month = value.month.toString().padLeft(2, '0');
    final day = value.day.toString().padLeft(2, '0');

    return '$year-$month-$day';
  }

  void dispose() {
    client.close();
  }
}
