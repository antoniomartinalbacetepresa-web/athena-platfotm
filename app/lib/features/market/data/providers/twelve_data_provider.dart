import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/market_data_point.dart';
import 'market_data_provider.dart';

/// Proveedor de datos de mercado basado en Twelve Data.
class TwelveDataProvider implements MarketDataProvider {
  static const String _providerId = 'twelve_data';

  final String apiKey;
  final http.Client client;
  final String baseUrl;

  TwelveDataProvider({
    required this.apiKey,
    http.Client? client,
    this.baseUrl = 'https://api.twelvedata.com',
  }) : client = client ?? http.Client();

  @override
  String get providerId => _providerId;

  @override
  Future<MarketDataPoint?> getQuote(String symbol) async {
    final normalizedSymbol = _normalizeSymbol(symbol);

    final uri = Uri.parse('$baseUrl/quote').replace(
      queryParameters: {
        'symbol': normalizedSymbol,
        'apikey': apiKey,
      },
    );

    final response = await client.get(uri);

    _validateResponse(response);

    final decoded = _decodeObject(response.body);

    if (_containsProviderError(decoded)) {
      throw Exception(
        decoded['message']?.toString() ??
            decoded['code']?.toString() ??
            'Twelve Data devolvió un error.',
      );
    }

    final price = _parseDouble(decoded['close']);

    if (price == null) {
      return null;
    }

    return MarketDataPoint(
      symbol: normalizedSymbol,
      timestamp: _parseTimestamp(decoded['datetime']),
      open: _parseDouble(decoded['open']),
      high: _parseDouble(decoded['high']),
      low: _parseDouble(decoded['low']),
      close: price,
      adjustedClose: price,
      volume: _parseDouble(decoded['volume']),
      change: _parseDouble(decoded['change']),
      changePercentage: _parseDouble(decoded['percent_change']),
      providerId: providerId,
    );
  }

  @override
  Future<List<MarketDataPoint>> getHistoricalData({
    required String symbol,
    DateTime? from,
    DateTime? to,
  }) async {
    final normalizedSymbol = _normalizeSymbol(symbol);

    final queryParameters = <String, String>{
      'symbol': normalizedSymbol,
      'interval': '1day',
      'outputsize': '5000',
      'apikey': apiKey,
    };

    if (from != null) {
      queryParameters['start_date'] = _formatDate(from);
    }

    if (to != null) {
      queryParameters['end_date'] = _formatDate(to);
    }

    final uri = Uri.parse('$baseUrl/time_series').replace(
      queryParameters: queryParameters,
    );

    final response = await client.get(uri);

    _validateResponse(response);

    final decoded = _decodeObject(response.body);

    if (_containsProviderError(decoded)) {
      throw Exception(
        decoded['message']?.toString() ??
            decoded['code']?.toString() ??
            'Twelve Data devolvió un error.',
      );
    }

    final values = decoded['values'];

    if (values == null) {
      return const [];
    }

    if (values is! List) {
      throw const FormatException(
        'La respuesta histórica de Twelve Data no contiene '
        'una lista válida.',
      );
    }

    final result = <MarketDataPoint>[];

    for (final item in values) {
      if (item is! Map) {
        continue;
      }

      result.add(
        MarketDataPoint(
          symbol: normalizedSymbol,
          timestamp: _parseTimestamp(item['datetime']),
          open: _parseDouble(item['open']),
          high: _parseDouble(item['high']),
          low: _parseDouble(item['low']),
          close: _parseDouble(item['close']),
          adjustedClose: _parseDouble(item['close']),
          volume: _parseDouble(item['volume']),
          providerId: providerId,
        ),
      );
    }

    return result;
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
    if (response.statusCode != 200) {
      throw Exception(
        'Twelve Data respondió con código HTTP '
        '${response.statusCode}.',
      );
    }
  }

  Map<String, dynamic> _decodeObject(String body) {
    final decoded = jsonDecode(body);

    if (decoded is! Map<String, dynamic>) {
      throw const FormatException(
        'La respuesta de Twelve Data no es un objeto JSON válido.',
      );
    }

    return decoded;
  }

  bool _containsProviderError(Map<String, dynamic> data) {
    return data['status']?.toString().toLowerCase() == 'error' ||
        (data['code'] != null &&
            data['values'] == null &&
            data['close'] == null);
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
      throw const FormatException(
        'Twelve Data no proporcionó fecha/hora.',
      );
    }

    final parsed = DateTime.tryParse(value.toString());

    if (parsed == null) {
      throw FormatException(
        'Fecha/hora inválida recibida de Twelve Data: $value',
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