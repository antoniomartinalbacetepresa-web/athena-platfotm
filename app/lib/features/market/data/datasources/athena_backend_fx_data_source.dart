import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../models/fx_quote.dart';

class AthenaBackendFxDataSource {
  final String baseUrl;
  final http.Client client;

  AthenaBackendFxDataSource({
    required this.baseUrl,
    http.Client? client,
  }) : client = client ?? http.Client();

  Future<FxQuote> getCurrentRate({
    required String baseCurrency,
    required String quoteCurrency,
  }) async {
    final base = _normalizeCurrency(baseCurrency, 'baseCurrency');
    final quote = _normalizeCurrency(quoteCurrency, 'quoteCurrency');

    final uri = Uri.parse('$baseUrl/api/v1/market/fx/quote').replace(
      queryParameters: {
        'base': base,
        'quote': quote,
      },
    );

    final response = await client.get(uri);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(
        'El backend de ATHENA TYCHE respondió con código HTTP '
        '${response.statusCode} al solicitar FX.',
      );
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw const FormatException(
        'La respuesta FX del backend no es un objeto JSON válido.',
      );
    }

    final data = decoded['data'];
    if (data is! Map) {
      throw const FormatException(
        'La respuesta FX del backend no contiene datos válidos.',
      );
    }

    final quoteResult = FxQuote.fromMap(Map<String, dynamic>.from(data));
    if (quoteResult.baseCurrency != base || quoteResult.quoteCurrency != quote) {
      throw const FormatException(
        'La respuesta FX no corresponde al par solicitado.',
      );
    }

    return quoteResult;
  }

  String _normalizeCurrency(String value, String field) {
    final normalized = value.trim().toUpperCase();
    if (!RegExp(r'^[A-Z]{3}$').hasMatch(normalized)) {
      throw ArgumentError.value(
        value,
        field,
        'Debe ser un código ISO de tres letras.',
      );
    }
    return normalized;
  }

  void dispose() {
    client.close();
  }
}
