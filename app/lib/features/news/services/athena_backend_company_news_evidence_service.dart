import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/company_news_evidence.dart';

/// Read-only company evidence. The server does not attest article truth or license.
class AthenaBackendCompanyNewsEvidenceService {
  static const defaultBackendUrl = String.fromEnvironment(
    'ATHENA_BACKEND_URL', defaultValue: 'http://127.0.0.1:8000',
  );

  final String baseUrl;
  final http.Client client;
  final Duration timeout;

  AthenaBackendCompanyNewsEvidenceService({
    this.baseUrl = defaultBackendUrl,
    http.Client? client,
    this.timeout = const Duration(seconds: 15),
  }) : client = client ?? http.Client();

  Future<CompanyNewsEvidence> getEvidence({
    required String symbol,
    required String companyName,
    int limit = 8,
  }) async {
    final normalizedSymbol = symbol.trim().toUpperCase();
    final normalizedName = companyName.trim();
    if (!RegExp(r'^[A-Z0-9][A-Z0-9.-]{0,19}$').hasMatch(normalizedSymbol) ||
        normalizedName.isEmpty || normalizedName.length > 100 ||
        normalizedName.contains('"') ||
        normalizedName.runes.any((code) => code < 32) ||
        limit < 1 || limit > 25) {
      throw ArgumentError('Consulta de empresa inválida.');
    }
    final uri = Uri.parse('$baseUrl/api/v1/news/company-evidence').replace(
      queryParameters: {
        'symbol': normalizedSymbol,
        'companyName': normalizedName,
        'limit': '$limit',
      },
    );
    final response = await client.get(uri).timeout(timeout);
    if (response.statusCode != 200) {
      throw StateError('La evidencia empresarial no está disponible.');
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map) {
      throw const FormatException('Respuesta empresarial inválida.');
    }
    return CompanyNewsEvidence.fromMap(
      Map<String, dynamic>.from(decoded),
      requestedSymbol: normalizedSymbol,
      requestedCompanyName: normalizedName,
    );
  }

  void dispose() => client.close();
}
