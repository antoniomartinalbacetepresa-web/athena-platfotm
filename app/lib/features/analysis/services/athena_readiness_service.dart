import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/operational_readiness.dart';
import '../models/market_history_gaps.dart';
import '../models/market_history_coverage.dart';

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

  /// Same PIT cutoff as the readiness report; never triggers ingestion.
  Future<MarketHistoryGapsPage> getMarketHistoryGaps({
    required DateTime asOf,
    int limit = 10,
    int offset = 0,
  }) async {
    if (limit < 1 || limit > 1000 || offset < 0) {
      throw const FormatException('Paginación de bloqueos PIT inválida.');
    }
    final uri = Uri.parse('$baseUrl/api/v1/readiness/market-history/gaps')
        .replace(queryParameters: {
      'asOf': asOf.toUtc().toIso8601String(),
      'limit': limit.toString(),
      'offset': offset.toString(),
    });
    final response = await client.get(uri);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception('Diagnóstico PIT no disponible.');
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map) {
      throw const FormatException('Diagnóstico PIT no es un objeto JSON.');
    }
    return MarketHistoryGapsPage.fromMap(
      Map<String, dynamic>.from(decoded),
      expectedAsOf: asOf,
    );
  }


  /// Read-only persisted PIT measurement at the readiness snapshot cutoff.
  Future<MarketHistoryCoverage> getMarketHistoryCoverage({
    required DateTime asOf,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/readiness/market-history/coverage')
        .replace(queryParameters: {
      'asOf': asOf.toUtc().toIso8601String(),
    });
    final response = await client.get(uri);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception('Cobertura histórica PIT no disponible.');
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map) {
      throw const FormatException('Cobertura histórica PIT no es un objeto JSON.');
    }
    return MarketHistoryCoverage.fromMap(
      Map<String, dynamic>.from(decoded),
      expectedAsOf: asOf,
    );
  }

  void dispose() {
    client.close();
  }
}
