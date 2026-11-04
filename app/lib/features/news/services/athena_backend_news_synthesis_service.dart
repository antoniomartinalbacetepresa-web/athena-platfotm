import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/verified_news_synthesis.dart';
import 'athena_backend_news_service.dart';

class AthenaBackendNewsSynthesisService {
  final String baseUrl;
  final http.Client client;
  final Duration requestTimeout;

  AthenaBackendNewsSynthesisService({
    this.baseUrl = AthenaBackendNewsService.defaultBackendUrl,
    http.Client? client,
    this.requestTimeout = const Duration(seconds: 15),
  }) : assert(requestTimeout > Duration.zero),
       client = client ?? http.Client();

  Future<VerifiedNewsSynthesis> getLatest() async {
    final uri = Uri.parse(
      '$baseUrl/api/v1/recommendations/professional-research/news-synthesis/latest',
    );
    final response = await client.get(uri).timeout(requestTimeout);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(
        'El backend de ATHENA TYCHE respondió con código HTTP '
        '${response.statusCode} al solicitar la síntesis News.',
      );
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map) {
      throw const FormatException('La síntesis News no es un objeto JSON válido.');
    }
    return VerifiedNewsSynthesis.fromMap(Map<String, dynamic>.from(decoded));
  }

  void dispose() => client.close();
}
