import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/relevant_investor_activity.dart';

class AthenaBackendRelevantInvestorDataSource {
  final String baseUrl;
  final http.Client client;

  AthenaBackendRelevantInvestorDataSource({
    required this.baseUrl,
    http.Client? client,
  }) : client = client ?? http.Client();

  Future<RelevantInvestorActivity> getLatestInstitutionalHoldings({
    required String cik,
  }) async {
    final normalizedCik = cik.trim();
    if (!RegExp(r'^\d{1,10}$').hasMatch(normalizedCik)) {
      throw ArgumentError.value(cik, 'cik', 'Debe contener entre 1 y 10 dígitos.');
    }

    final uri = Uri.parse('$baseUrl/api/v1/sec/institutional-holdings/latest')
        .replace(queryParameters: {'cik': normalizedCik});
    final response = await client.get(uri);
    if (response.statusCode == 404) {
      throw StateError('No hay filings 13F recientes para este CIK.');
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(
        'El backend de ATHENA TYCHE respondió con código HTTP '
        '${response.statusCode} al consultar SEC 13F.',
      );
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw const FormatException('La respuesta SEC 13F no es un objeto JSON.');
    }
    return RelevantInvestorActivity.fromApi(
      cik: normalizedCik,
      envelope: decoded,
    );
  }

  void dispose() {
    client.close();
  }
}
