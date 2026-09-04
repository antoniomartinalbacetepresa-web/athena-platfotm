import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/portfolio_pair_correlation.dart';

class AthenaBackendPortfolioCorrelationDataSource {
  final String baseUrl;
  final http.Client client;

  AthenaBackendPortfolioCorrelationDataSource({
    required this.baseUrl,
    http.Client? client,
  }) : client = client ?? http.Client();

  Future<PortfolioPairCorrelation> getPair({
    required int leftInstrumentId,
    required int rightInstrumentId,
    required String sourceProvider,
    required DateTime knowledgeCutoff,
    DateTime? observedFrom,
    DateTime? observedTo,
  }) async {
    if (leftInstrumentId <= 0 || rightInstrumentId <= 0) {
      throw ArgumentError('Los instrumentId deben ser positivos.');
    }
    if (leftInstrumentId == rightInstrumentId) {
      throw ArgumentError('La correlación requiere instrumentos distintos.');
    }
    final provider = sourceProvider.trim();
    if (provider.isEmpty) {
      throw ArgumentError.value(sourceProvider, 'sourceProvider', 'No puede estar vacío.');
    }
    if (!knowledgeCutoff.isUtc) {
      throw ArgumentError.value(
        knowledgeCutoff,
        'knowledgeCutoff',
        'Debe expresarse explícitamente en UTC.',
      );
    }
    if (observedFrom != null && !observedFrom.isUtc) {
      throw ArgumentError.value(observedFrom, 'observedFrom', 'Debe ser UTC.');
    }
    if (observedTo != null && !observedTo.isUtc) {
      throw ArgumentError.value(observedTo, 'observedTo', 'Debe ser UTC.');
    }
    if (observedFrom != null &&
        observedTo != null &&
        observedTo.isBefore(observedFrom)) {
      throw ArgumentError('observedTo no puede preceder a observedFrom.');
    }

    final query = <String, String>{
      'leftInstrumentId': leftInstrumentId.toString(),
      'rightInstrumentId': rightInstrumentId.toString(),
      'sourceProvider': provider,
      'knowledgeCutoff': knowledgeCutoff.toIso8601String(),
      if (observedFrom != null) 'observedFrom': observedFrom.toIso8601String(),
      if (observedTo != null) 'observedTo': observedTo.toIso8601String(),
    };
    final uri = Uri.parse('$baseUrl/api/v1/portfolio/correlation')
        .replace(queryParameters: query);
    final response = await client.get(uri);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(
        'El backend de ATHENA TYCHE respondió con código HTTP '
        '${response.statusCode} al calcular correlación PIT.',
      );
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw const FormatException('La respuesta de correlación no es un objeto JSON.');
    }
    final data = decoded['data'];
    if (data is! Map) {
      throw const FormatException('La respuesta no contiene datos de correlación.');
    }

    final result = PortfolioPairCorrelation.fromMap(
      Map<String, dynamic>.from(data),
    );
    if (result.leftInstrumentId != leftInstrumentId ||
        result.rightInstrumentId != rightInstrumentId) {
      throw const FormatException(
        'La correlación devuelta pertenece a instrumentos distintos de los solicitados.',
      );
    }
    if (result.sourceProvider != provider) {
      throw const FormatException(
        'La correlación devuelta no corresponde al proveedor solicitado.',
      );
    }
    if (!result.knowledgeCutoff.isAtSameMomentAs(knowledgeCutoff)) {
      throw const FormatException(
        'La correlación devuelta no corresponde al knowledgeCutoff solicitado.',
      );
    }

    return result;
  }

  void dispose() {
    client.close();
  }
}
