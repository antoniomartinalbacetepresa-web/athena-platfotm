import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/portfolio_instrument_identity.dart';

class AthenaBackendPortfolioIdentityDataSource {
  final String baseUrl;
  final http.Client client;

  AthenaBackendPortfolioIdentityDataSource({
    required this.baseUrl,
    http.Client? client,
  }) : client = client ?? http.Client();

  Future<PortfolioInstrumentIdentity> resolve({
    required String symbol,
    String? exchange,
  }) async {
    final normalizedSymbol = symbol.trim().toUpperCase();
    if (normalizedSymbol.isEmpty) {
      throw ArgumentError.value(symbol, 'symbol', 'No puede estar vacío.');
    }
    final normalizedExchange = exchange?.trim().toUpperCase();

    final query = <String, String>{'symbol': normalizedSymbol};
    if (normalizedExchange != null && normalizedExchange.isNotEmpty) {
      query['exchange'] = normalizedExchange;
    }

    final uri = Uri.parse('$baseUrl/api/v1/portfolio/instrument-identity')
        .replace(queryParameters: query);
    final response = await client.get(uri);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(
        'El backend de ATHENA TYCHE respondió con código HTTP '
        '${response.statusCode} al resolver identidad de cartera.',
      );
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw const FormatException(
        'La respuesta de identidad no es un objeto JSON válido.',
      );
    }
    final data = decoded['data'];
    if (data is! Map) {
      throw const FormatException(
        'La respuesta de identidad no contiene datos válidos.',
      );
    }

    final identity = PortfolioInstrumentIdentity.fromMap(
      Map<String, dynamic>.from(data),
    );
    if (identity.symbol != normalizedSymbol) {
      throw const FormatException(
        'La identidad resuelta no corresponde al símbolo solicitado.',
      );
    }
    if (identity.isRiskReady) {
      if (normalizedExchange == null || normalizedExchange.isEmpty) {
        throw const FormatException(
          'Una identidad apta para riesgo requiere exchange solicitado.',
        );
      }
      final exchangeMatches = identity.exchange == normalizedExchange ||
          identity.exchangeShortName == normalizedExchange;
      if (!exchangeMatches) {
        throw const FormatException(
          'La identidad apta para riesgo no corresponde al exchange solicitado.',
        );
      }
    }

    return identity;
  }

  void dispose() {
    client.close();
  }
}
