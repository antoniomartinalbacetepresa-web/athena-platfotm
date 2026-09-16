import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/verified_news_feed.dart';

class AthenaBackendNewsService {
  static const String defaultBackendUrl = String.fromEnvironment(
    'ATHENA_BACKEND_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );

  final String baseUrl;
  final http.Client client;

  AthenaBackendNewsService({
    this.baseUrl = defaultBackendUrl,
    http.Client? client,
  }) : client = client ?? http.Client();

  Future<VerifiedNewsFeed> getFeed({
    String? query,
    int limit = 8,
    String language = 'en',
    String country = 'US',
  }) async {
    if (limit < 1 || limit > 25) {
      throw ArgumentError.value(limit, 'limit', 'Debe estar entre 1 y 25.');
    }

    final normalizedLanguage = _localePart(language, 'language').toLowerCase();
    final normalizedCountry = _localePart(country, 'country').toUpperCase();
    final normalizedQuery = query?.trim();
    if (normalizedQuery != null && normalizedQuery.isEmpty) {
      throw ArgumentError.value(query, 'query', 'No puede estar vacía.');
    }
    if (normalizedQuery != null && normalizedQuery.length > 200) {
      throw ArgumentError.value(query, 'query', 'Supera 200 caracteres.');
    }

    final params = <String, String>{
      'limit': '$limit',
      'language': normalizedLanguage,
      'country': normalizedCountry,
      if (normalizedQuery != null) 'query': normalizedQuery,
    };
    final uri = Uri.parse('$baseUrl/api/v1/news/feed').replace(
      queryParameters: params,
    );

    final response = await client.get(uri);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(
        'El backend de ATHENA TYCHE respondió con código HTTP '
        '${response.statusCode} al solicitar noticias.',
      );
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map) {
      throw const FormatException(
        'La respuesta de noticias no es un objeto JSON válido.',
      );
    }
    return VerifiedNewsFeed.fromMap(Map<String, dynamic>.from(decoded));
  }

  String _localePart(String value, String field) {
    final normalized = value.trim();
    if (!RegExp(r'^[A-Za-z]{2}$').hasMatch(normalized)) {
      throw ArgumentError.value(
        value,
        field,
        'Debe ser un código de dos letras.',
      );
    }
    return normalized;
  }

  void dispose() {
    client.close();
  }
}
