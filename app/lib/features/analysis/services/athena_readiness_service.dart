import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/operational_readiness.dart';

class AthenaReadinessService {
  static const String defaultBackendUrl = String.fromEnvironment(
    'ATHENA_BACKEND_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );

  AthenaReadinessService({
    this.baseUrl = defaultBackendUrl,
    http.Client? client,
  }) : client = client ?? http.Client();

  final String baseUrl;
  final http.Client client;

  Future<AthenaReadinessReport> getReport() async {
    final response = await client.get(Uri.parse('$baseUrl/api/v1/readiness'));
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(
        'El backend de ATHENA respondió con código HTTP '
        '${response.statusCode} al solicitar readiness.',
      );
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map) {
      throw const FormatException('La respuesta de readiness no es un objeto JSON.');
    }
    return AthenaReadinessReport.fromMap(Map<String, dynamic>.from(decoded));
  }

  void dispose() {
    client.close();
  }
}
