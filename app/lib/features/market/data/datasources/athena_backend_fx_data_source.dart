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

    return _loadQuote(uri, expectedBase: base, expectedQuote: quote);
  }

  Future<FxQuote> getHistoricalRate({
    required String baseCurrency,
    required String quoteCurrency,
    required DateTime observedOn,
    DateTime? knowledgeCutoff,
  }) async {
    final base = _normalizeCurrency(baseCurrency, 'baseCurrency');
    final quote = _normalizeCurrency(quoteCurrency, 'quoteCurrency');
    final observedDate = observedOn.toUtc();
    final cutoff = knowledgeCutoff?.toUtc();

    final query = <String, String>{
      'base': base,
      'quote': quote,
      'observedOn': _formatDate(observedDate),
    };
    if (cutoff != null) {
      query['knowledgeCutoff'] = cutoff.toIso8601String();
    }

    final uri = Uri.parse('$baseUrl/api/v1/market/fx/historical').replace(
      queryParameters: query,
    );
    final result = await _loadQuote(
      uri,
      expectedBase: base,
      expectedQuote: quote,
    );

    if (!_sameUtcDate(result.observedAt, observedDate)) {
      throw const FormatException(
        'La respuesta FX histórica no corresponde a la fecha solicitada.',
      );
    }
    if (cutoff != null && result.retrievedAt.isAfter(cutoff)) {
      throw const FormatException(
        'La respuesta FX histórica fue recuperada después del knowledge cutoff.',
      );
    }

    return result;
  }

  Future<FxQuote> _loadQuote(
    Uri uri, {
    required String expectedBase,
    required String expectedQuote,
  }) async {
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
    if (quoteResult.baseCurrency != expectedBase ||
        quoteResult.quoteCurrency != expectedQuote) {
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

  String _formatDate(DateTime value) {
    final year = value.year.toString().padLeft(4, '0');
    final month = value.month.toString().padLeft(2, '0');
    final day = value.day.toString().padLeft(2, '0');
    return '$year-$month-$day';
  }

  bool _sameUtcDate(DateTime left, DateTime right) {
    final a = left.toUtc();
    final b = right.toUtc();
    return a.year == b.year && a.month == b.month && a.day == b.day;
  }

  void dispose() {
    client.close();
  }
}
